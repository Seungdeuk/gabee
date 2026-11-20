"""탐정단 사진 추천의 내용 질문: 사진 한 장을 AI 에 보내 선택식 문제 하나를 받는다.

- AI 에는 사진(`photo_judge.to_judge_jpeg` 로 EXIF 를 지운 1024px JPEG) 한 장만 보낸다. 일정·가족 정보는 보내지 않는다.
- AI 는 쓸 수 있는 사진인지(`usable`), 질문(20자 이하), 보기 2~4개, 정답 위치, 확대할 위치(0~1)를 돌려준다.
  사람 얼굴이 크게 나오거나 글자·서류 사진이면 `usable=false` 다. 서버는 모양만 검사한다(사실인지는 판단하지 않는다).
- 사진 한 장당 AI 한 번(규칙에 안 맞으면 한 번 더). 한도는 `play_photo_rec` 묶음으로 따로 센다.
"""

import math
from dataclasses import dataclass

from app.shared import ai_guard
from app.shared.config import settings
from app.shared.llm import client as llm

FEATURE = "play_photo_rec"
PROMPT_VERSION = "v1"  # 프롬프트·스키마를 바꾸면 올려서 오래된 결과를 구분한다
QUESTION_MAX = 20
OPTION_MIN, OPTION_MAX = 2, 4
OPTION_LEN_MAX = 20
MAX_TOKENS = 4000  # 생각 토큰이 출력 한도를 같이 쓴다(draw_rec 와 같은 이유). 쓴 만큼만 과금된다
TIMEOUT = 60.0
EFFORT = "low"

SYSTEM = (
    "당신은 가족 퀴즈 '탐정단'에 낼 사진 문제를 만드는 비서입니다. 사진에 보이는 것만 묻는 "
    "선택식 문제 한 개를 만듭니다. 사진에서 분명히 확인되는 사실만 묻고 추측이 필요한 것은 묻지 않습니다. "
    "사람 얼굴이 크게 나오거나 글자·서류 사진이면 문제를 만들지 말고 usable=false 로 답합니다."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer_index": {"type": "integer"},
        "box_x": {"type": "number"},
        "box_y": {"type": "number"},
    },
    "required": ["usable", "question", "options", "answer_index", "box_x", "box_y"],
    "additionalProperties": False,
}


def content_prompt() -> str:
    """사진 한 장에 대한 요청. 사진 외의 정보는 들어가지 않는다."""
    return (
        "첨부한 사진 한 장으로 문제를 만드세요.\n"
        "- 사람 얼굴이 크게 나오거나 글자·서류 사진이면 usable=false 로 답하고 나머지 칸은 비우거나 0 으로 둡니다.\n"
        f"- 질문은 {QUESTION_MAX}자 이하입니다. 사진에 보이는 것을 묻는 선택식 문제입니다.\n"
        f"- 보기는 {OPTION_MIN}~{OPTION_MAX}개이고 각 {OPTION_LEN_MAX}자 이하, 서로 달라야 합니다. "
        "정답은 보기 중 하나이며 answer_index 는 그 보기의 위치(0부터)입니다.\n"
        "- 정답이 사진에서 분명히 확인돼야 합니다. 헷갈리는 보기는 피합니다.\n"
        "- box_x, box_y 는 확대해서 보여 주면 재미있을 위치(사진의 가로·세로 0~1, 왼쪽 위가 0)입니다."
    )


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_content(raw: object) -> dict | None:
    """모델이 돌려준 값이 규칙에 맞으면 {usable, question, options, answer_index, box_x, box_y} 로 돌려주고 아니면 None.
    `usable=false` 는 질문·보기 없이도 통과한다(그 사진은 쓰지 않는다고 저장한다)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("usable"), bool):
        return None
    if raw["usable"] is False:
        return {
            "usable": False,
            "question": "",
            "options": [],
            "answer_index": 0,
            "box_x": 0.5,
            "box_y": 0.5,
        }
    question, options = raw.get("question"), raw.get("options")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= QUESTION_MAX:
        return None
    if not isinstance(options, list) or not OPTION_MIN <= len(options) <= OPTION_MAX:
        return None
    if any(not isinstance(o, str) or not 1 <= len(o.strip()) <= OPTION_LEN_MAX for o in options):
        return None
    cleaned = [o.strip() for o in options]
    if len(set(cleaned)) != len(cleaned):
        return None
    index = raw.get("answer_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(cleaned):
        return None
    box_x, box_y = raw.get("box_x"), raw.get("box_y")
    if not (_is_number(box_x) and _is_number(box_y)):
        return None
    if not (0 <= box_x <= 1 and 0 <= box_y <= 1):
        return None
    return {
        "usable": True,
        "question": question.strip(),
        "options": cleaned,
        "answer_index": index,
        "box_x": float(box_x),
        "box_y": float(box_y),
    }


@dataclass(frozen=True)
class ContentResult:
    """사진 한 장의 내용 질문과 쓴 토큰(다시 시도 포함). 호출한 쪽이 ai_guard 의 사용량으로 센다."""

    usable: bool
    question: str
    options: list[str]
    answer_index: int
    box_x: float
    box_y: float
    input_tokens: int
    output_tokens: int
    model: str


class ContentFailed(ValueError):
    """두 번 시도해도 규칙에 맞는 문제를 받지 못했다. 쓴 호출·토큰을 같이 알려 준다(ai_guard 가 센다)."""

    def __init__(self, message: str, calls: int, input_tokens: int, output_tokens: int):
        super().__init__(message)
        self.calls = calls
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def content_question(jpeg: bytes) -> ContentResult:
    """사진(JPEG) 한 장의 내용 질문을 AI 로 만든다. 규칙에 안 맞으면 한 번 더 시도하고, 그래도 안 되면 ContentFailed.
    AI 가 안 되면 llm.LLMUnavailable 이 그대로 올라간다."""
    tokens_in = tokens_out = calls = 0
    for _ in range(2):
        result = llm.complete_json(
            content_prompt(),
            SCHEMA,
            system=SYSTEM,
            max_tokens=MAX_TOKENS,
            effort=EFFORT,
            timeout=TIMEOUT,
            images=[jpeg],
        )
        calls += 1
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        valid = validate_content(result.data)
        if valid is not None:
            return ContentResult(
                **valid, input_tokens=tokens_in, output_tokens=tokens_out, model=result.model
            )
    raise ContentFailed("사진 문제가 규칙에 맞지 않아요", calls, tokens_in, tokens_out)


def register_limits() -> None:
    """사진 추천의 내용 질문은 기본 한도와 따로 센다."""
    ai_guard.register_bucket(
        FEATURE,
        ai_guard.Limits(
            settings.ai_play_photo_rec_cooldown_seconds,
            settings.ai_play_photo_rec_max_calls_per_user_per_day,
            settings.ai_play_photo_rec_max_calls_per_group_per_day,
        ),
        (FEATURE,),
    )


register_limits()
