"""찰칵 흔한 사진 자동 보충의 질문 만들기: 공개 사진(Pixabay) 한 장을 AI 에 보내 흔한 사진용 선택식 문제 하나를 받는다.

- 가족 정보·`ai_guard` 를 쓰지 않는다(공개 사진뿐이다). 호출 수는 `photo_rec_auto.run_daily` 의 하루 목표·시도 상한이 묶는다.
- 사진 한 장당 AI 한 번만 부른다(규칙에 안 맞으면 재시도 없이 `Rejected`, 다음 후보로 넘어가는 건 부르는 쪽).
- 서버 규칙 검사 `photo_rec_ai.validate_content` 를 먼저 통과해야 하고, 그 위에 시드 기준(소재·금지어·질문 형태·보기 길이)을 더한다.
"""

import re
from dataclasses import dataclass

from app.shared.llm import client as llm

from .photo_rec_ai import EFFORT, MAX_TOKENS, QUESTION_MAX, SCHEMA, TIMEOUT, validate_content

PROMPT_VERSION = "auto-v1"  # 프롬프트·규칙을 바꾸면 올려서 오래된 결과를 구분한다
MAX_OPTION_WORDS = 2

ALLOWED_FLOWERS = "민들레 개나리 튤립 무궁화 해바라기 카네이션 코스모스 장미 진달래 벚꽃 목련 철쭉 팬지 프리지아 백합".split()
BANNED_WORDS = (
    # 장례 느낌·낯선 꽃
    "국화",
    "소국",
    "할미꽃",
    "구절초",
    # 무섭거나 징그러운 동물
    "뱀",
    "도마뱀",
    "곤충",
    "파충류",
    "거미",
    "벌레",
    "악어",
    "전갈",
    "지네",
    "개구리",
    "바퀴",
    # 술
    "맥주",
    "와인",
    "소주",
    "막걸리",
    "위스키",
    "칵테일",
    "술",
    # 사람
    "사람",
)
COLORS = {"빨강", "파랑", "노랑", "초록", "주황", "보라", "분홍", "하양", "검정", "갈색", "흰색"}
_QUESTION_FORMS = (
    re.compile(r"^무슨 (음식|과일|꽃|동물|채소|빵|간식|음료|탈것|물건)(일까요|이에요|인가요)\?$"),
    re.compile(r"^(이게 |이것은 )?(무엇|뭘까|뭐)(일까요|이에요|예요|인가요|요)?\?$"),
    re.compile(r"^(여기는 |이곳은 )?어디(일까요|예요|인가요)\?$"),
    re.compile(r"^어느 계절(일까요| 같아요| 같나요)\?$"),
)
_INDIRECT = ("어울", "한식", "양식", "중식", "일식")

SYSTEM = (
    "당신은 가족 퀴즈 '탐정단'에 낼 흔한 사진 문제를 만드는 비서입니다. 누구나 한눈에 알아볼 수 있는 "
    "일상 사진에 대해, 사진에서 분명히 확인되는 것만 직접 묻는 선택식 문제 한 개를 만듭니다. "
    "조금이라도 애매하거나 소재가 맞지 않으면 문제를 만들지 말고 usable=false 로 답합니다."
)


def prompt() -> str:
    """사진 한 장에 대한 요청. 사진 외의 정보는 들어가지 않는다."""
    return (
        "첨부한 사진 한 장으로 문제를 만드세요.\n"
        "- 쓸 수 있는 소재: 일상·친숙한 완성된 음식, 과일, 친숙한 동물, 흔한 꽃, 익숙한 장소, 계절 풍경, 일상 물건. "
        "아래에 해당하면 usable=false 로 답하고 나머지 칸은 비우거나 0 으로 둡니다.\n"
        "- 쓸 수 없는 것: 뱀·곤충·파충류·거미 같은 무섭거나 징그러운 동물, 낯선 풍경, 술, "
        "읽을 수 있는 글자·브랜드, 국화 같은 장례 느낌 꽃, 병원 같은 부정적 장소, 정적이거나 무엇인지 알아보기 어려운 사진.\n"
        f'- 질문은 {QUESTION_MAX}자 이하이고 직접 묻습니다: 음식·과일·꽃·동물은 "무슨 음식일까요?"·"무슨 과일일까요?"·'
        '"무슨 꽃일까요?"·"무슨 동물일까요?" 처럼, 장소는 "어디일까요?", 계절은 "어느 계절 같아요?", 물건은 "무엇일까요?" 로 묻습니다.\n'
        '- "어울릴까요?"·"한식일까요?" 같은 간접 질문과 색깔을 묻는 질문은 쓰지 않습니다.\n'
        "- 보기는 2~4개이고 각각 한두 단어(20자 이하)이며 서로 달라야 합니다. 정답은 보기 중 하나이고 answer_index 는 그 위치(0부터)입니다. "
        "헷갈리는 보기는 피합니다.\n"
        "- 사진에 사람이 함께 찍혀 있어도 됩니다. 다만 사람·얼굴을 묻는 문제는 만들지 않고 보기에도 사람을 넣지 않습니다. "
        "장소 문제는 서로 헷갈리는 비슷한 장소(예: 서점과 도서관)를 보기에 함께 넣지 않습니다.\n"
        f"- 꽃은 정답·보기에 흔한 꽃({', '.join(ALLOWED_FLOWERS)})만 씁니다. 할미꽃·국화·소국 등은 쓰지 않습니다.\n"
        "- box_x, box_y 는 확대해서 보여 주면 재미있을 위치(사진의 가로·세로 0~1, 왼쪽 위가 0)입니다."
    )


class Rejected(ValueError):
    """AI 가 돌려준 문제가 규칙에 안 맞는다(사진은 버리고 다음 후보로)."""


@dataclass(frozen=True)
class AutoQuestion:
    """공개 사진 한 장의 문제. `usable=False` 면 그 사진은 쓰지 않는다."""

    usable: bool
    question: str
    options: list[str]
    answer_index: int
    box_x: float
    box_y: float
    tokens: int


def check_rules(valid: dict) -> str | None:
    """`validate_content` 를 통과한 usable 문제가 시드 기준에 맞으면 None, 아니면 이유."""
    question, options = valid["question"], valid["options"]
    text = [question, *options]
    for word in BANNED_WORDS:
        if any(word in t for t in text):
            return f"금지어 {word}"
    if "색" in question or set(options) <= COLORS:
        return "색깔 질문"
    if any(word in question for word in _INDIRECT):
        return "간접 질문"
    if not any(form.match(question) for form in _QUESTION_FORMS):
        return "질문 형태"
    if any(len(o.split()) > MAX_OPTION_WORDS for o in options):
        return "보기가 길어요"
    if "꽃" in question and not all(any(f in o for f in ALLOWED_FLOWERS) for o in options):
        return "허용 목록 밖의 꽃"
    return None


def make_question(jpeg: bytes) -> AutoQuestion:
    """사진(JPEG) 한 장의 문제를 만든다. AI 한 번. 규칙에 안 맞으면 `Rejected`, AI 가 안 되면 `llm.LLMUnavailable` 이 그대로 올라간다."""
    result = llm.complete_json(
        prompt(),
        SCHEMA,
        system=SYSTEM,
        max_tokens=MAX_TOKENS,
        effort=EFFORT,
        timeout=TIMEOUT,
        images=[jpeg],
    )
    tokens = result.input_tokens + result.output_tokens
    valid = validate_content(result.data)
    if valid is None:
        raise Rejected("형식이 규칙에 안 맞음")
    if not valid["usable"]:
        return AutoQuestion(False, "", [], 0, 0.5, 0.5, tokens)
    reason = check_rules(valid)
    if reason is not None:
        raise Rejected(reason)
    return AutoQuestion(
        True,
        valid["question"],
        valid["options"],
        valid["answer_index"],
        valid["box_x"],
        valid["box_y"],
        tokens,
    )
