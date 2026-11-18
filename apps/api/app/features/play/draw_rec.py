"""이게 뭐게 가비 추천: 서버가 공개 단어 목록에서 한 단어씩 뽑고, AI 가 단어마다 선 좌표 그림을 만들어 준다.

- 단어: `draw_words.json` 의 흔한 사물 한 단어. 가족 일정·대화에서 목록에 있는 단어를 찾고 부족하면 흔한 단어로 채운다(이 모듈 아래쪽).
  일정·대화 원문은 AI 로 보내지 않는다. AI 는 단어 하나만 받아 선 그림을 그린다.
- 그림: 어린이가 손으로 그린 듯한 낙서(선 3~12개, 선마다 점 2~30개, 좌표 0~255). 서버는 모양만 검사한다(알아볼 수 있는지는 판단하지 않는다).
"""

import hashlib
import math
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_chat import ai_repository
from app.features.family_group.models import User
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm import client as llm

from . import draw_stock, draw_words, quiz_rec
from .constants import GAME_DRAW
from .models import PlayDraw, PlayItem
from .timeutil import aware, local_day_start, local_tz

FEATURE = "play_draw_rec"
PROMPT_VERSION = "v1"  # 프롬프트·스키마를 바꾸면 올려서 오래된 캐시를 쓰지 않게 한다
ASK_COUNT = 5  # 한 번 열 때 보여 주는 그림 수
PARTIAL = "partial"  # 그림이 5개가 안 된다: 있는 그림은 보여 주고, 다시 불러오면(한도 안에서) 모자란 만큼 더 채운다
REDRAW_RATE = 0.3  # 저장된 그림이 있어도 새로 그리는 확률
RECENT_DAYS = 30  # 최근에 낸 단어를 빼는 기간
EVENT_PAST_DAYS = 30
EVENT_AHEAD_DAYS = 30
CHAT_DAYS = 14

STROKE_MIN, STROKE_MAX = 3, 12
POINT_MIN, POINT_MAX = 2, 30
COORD_MAX = 255
MAX_TOKENS = 3000  # 생각 토큰이 출력 한도를 같이 쓴다(quiz_rec 와 같은 이유). 쓴 만큼만 과금된다
TIMEOUT = 60.0
EFFORT = "low"  # 그림은 깊이 생각할 필요가 없다

SYSTEM = (
    "당신은 가족 퀴즈 '이게 뭐게'에 낼 그림을 그려 주는 비서입니다. 주어진 사물을 "
    "어린이가 손으로 쓱쓱 그린 듯한 단순한 외곽선 그림으로 그립니다. "
    "그림은 선(점을 이은 선) 목록의 좌표로만 돌려줍니다."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "strokes": {
            "type": "array",
            "items": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
        }
    },
    "required": ["strokes"],
    "additionalProperties": False,
}


def draw_prompt(word: str) -> str:
    """단어 하나를 그리게 하는 요청. 가족 정보는 들어가지 않는다."""
    return (
        f"그릴 것: {word}\n"
        "- 어린이가 손으로 삐뚤빼뚤 그린 듯한 단순한 낙서 느낌의 외곽선 그림입니다. 가족이 보면 바로 알아맞힐 수 있게 그 사물의 가장 "
        "대표적인 특징(실루엣)을 살립니다.\n"
        f"- 좌표는 가로세로 0~{COORD_MAX} 정사각형이고 왼쪽 위가 (0,0)입니다. 그림이 칸 가득(여백 20 정도) 보이게 그립니다.\n"
        f"- strokes 는 선 목록이고 선은 {STROKE_MIN}~{STROKE_MAX}개, 선 하나는 점 {POINT_MIN}~{POINT_MAX}개입니다. "
        "곡선과 동그라미는 점을 촘촘히 찍어 부드럽게 만듭니다.\n"
        "- 글자, 숫자, 화살표, 색칠은 넣지 않습니다. 정답을 글자로 쓰지 않습니다."
    )


def validate_strokes(raw: object) -> list[list[list[int]]] | None:
    """모델이 돌려준 선 목록이 규칙(선·점 개수, 좌표 0~255, 숫자)에 맞으면 정수 좌표로 고쳐 돌려주고 아니면 None."""
    if not isinstance(raw, list) or not STROKE_MIN <= len(raw) <= STROKE_MAX:
        return None
    strokes = []
    for stroke in raw:
        if not isinstance(stroke, list) or not POINT_MIN <= len(stroke) <= POINT_MAX:
            return None
        points = []
        for point in stroke:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                return None
            if any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in point
            ):
                return None
            x, y = round(point[0]), round(point[1])
            if not (0 <= x <= COORD_MAX and 0 <= y <= COORD_MAX):
                return None
            points.append([x, y])
        strokes.append(points)
    return strokes


@dataclass(frozen=True)
class DrawUsage:
    """그림 하나를 만드는 데 쓴 호출(다시 시도 포함)의 합. ai_guard 가 한도·비용으로 센다."""

    input_tokens: int
    output_tokens: int
    model: str | None
    calls: int


class DrawFailed(ValueError):
    """두 번 시도해도 규칙에 맞는 그림을 받지 못했다. 쓴 호출·토큰을 같이 알려 준다(ai_guard 가 센다)."""

    def __init__(self, message: str, calls: int, input_tokens: int, output_tokens: int):
        super().__init__(message)
        self.calls = calls
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def draw_word(word: str) -> tuple[list[list[list[int]]], DrawUsage]:
    """단어 하나의 선 그림을 AI 로 만든다. 규칙에 안 맞으면 한 번 더 시도하고, 그래도 안 되면 DrawFailed."""
    tokens_in = tokens_out = calls = 0
    model = None
    for _ in range(2):
        result = llm.complete_json(
            draw_prompt(word),
            SCHEMA,
            system=SYSTEM,
            max_tokens=MAX_TOKENS,
            effort=EFFORT,
            timeout=TIMEOUT,
        )
        calls += 1
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        model = result.model
        strokes = validate_strokes(result.data.get("strokes"))
        if strokes is not None:
            return strokes, DrawUsage(tokens_in, tokens_out, model, calls)
    raise DrawFailed(f"그림이 규칙에 맞지 않아요: {word}", calls, tokens_in, tokens_out)


# ---------- 추천 조립 ----------
CHAT_MESSAGE_LIMIT = 500  # DB 에서 가져오는 최근 메시지 수 상한(골든벨 `chat_digest` 와 같다)
_norm = quiz_rec._norm  # 글자 비교용: 공백을 없애고 소문자로


def register_limits() -> None:
    """이게 뭐게 추천은 기본 한도와 따로 센다. 한 번에 그림 5개를 부르므로 한도는 호출 수 기준이다."""
    ai_guard.register_bucket(
        FEATURE,
        ai_guard.Limits(
            settings.ai_play_draw_rec_cooldown_seconds,
            settings.ai_play_draw_rec_max_calls_per_user_per_day,
            settings.ai_play_draw_rec_max_calls_per_group_per_day,
        ),
        (FEATURE,),
    )


register_limits()


def daily_rng(group_id: str, today: date) -> random.Random:
    """가족·날짜로 시드한 난수. 캐시가 풀려도 같은 날 같은 가족은 같은 단어가 나온다."""
    seed = int(hashlib.sha256(f"{group_id}|{today.isoformat()}".encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def family_words(db: Session, group_id: str, today: date, now: datetime) -> list[tuple[str, str]]:
    """가족 일정(공동 일정 원본)과 가족 전체방 최근 대화에서 목록 단어를 찾는다. (단어, "schedule"|"chat"), 일정 먼저·중복 없음.
    1:1 방·개인 AI 방은 읽지 않고(`ai_repository.recent_messages` 가 가족 전체방만 준다) 글자는 AI 로 보내지 않는다."""
    found: dict[str, str] = {}
    for event in quiz_rec.shared_events(db, group_id, today):
        text = " ".join([event.title or "", event.place or "", event.memo or ""])
        for word in draw_words.find_words(text):
            found.setdefault(word, "schedule")
    cutoff = now - timedelta(days=CHAT_DAYS)
    for message, _name in ai_repository.recent_messages(db, group_id, CHAT_MESSAGE_LIMIT):
        if aware(message.created_at) >= cutoff:
            for word in draw_words.find_words(message.text):
                found.setdefault(word, "chat")
    return list(found.items())


def recent_words(db: Session, group_id: str, now: datetime) -> set[str]:
    """이 가족이 최근 30일 안에 이게 뭐게에서 낸 정답과 비슷한 정답(글자 비교용으로 다듬은 것)."""
    since = now - timedelta(days=RECENT_DAYS)
    rows = db.execute(
        select(PlayDraw.answer, PlayDraw.alt_answers)
        .join(PlayItem, PlayItem.id == PlayDraw.play_id)
        .where(
            PlayItem.group_id == group_id, PlayItem.game == GAME_DRAW, PlayItem.created_at >= since
        )
    ).all()
    words: set[str] = set()
    for answer, alts in rows:
        for text in (answer, *(alts or [])):
            if text:
                words.add(_norm(text))
    return words


def pick_words(
    found: list[tuple[str, str]], recent: set[str], rng: random.Random
) -> list[tuple[str, str]]:
    """가족 재료의 단어를 먼저 쓰고(5개보다 많으면 난수로 5개), 모자라면 목록의 흔한 단어("common")로 채운다.
    최근에 낸 단어(비슷한 정답 포함)는 뺀다. 후보가 모자라면 있는 만큼만 돌려준다."""
    words = draw_words.load_words()

    def used(word: str) -> bool:
        return any(_norm(x) in recent for x in (word, *words[word].alts))

    chosen = [(w, s) for w, s in found if w in words and not used(w)]
    if len(chosen) > ASK_COUNT:
        chosen = rng.sample(chosen, ASK_COUNT)
    taken = {w for w, _ in chosen}
    pool = sorted(w for w in words if w not in taken and not used(w))
    need = ASK_COUNT - len(chosen)
    if need > 0 and pool:
        chosen += [(w, "common") for w in rng.sample(pool, min(need, len(pool)))]
    return chosen


@dataclass(frozen=True)
class _Batch:
    """ai_guard 가 사용 기록·한도에 세는 값. 그림을 몇 번 불렀든 추천 한 번을 한도 1회(`calls`)로 센다(성공하면 하루 캐시라 2·3회는
    실패했을 때의 다시 시도분이다). 비용에 쓰는 토큰은 실제로 부른 만큼 센다."""

    model: str
    input_tokens: int
    output_tokens: int
    calls: int = 1


def _cache_key(today: date) -> str:
    raw = f"{PROMPT_VERSION}|{FEATURE}|{settings.llm_model}|{today.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _reply(state: str, items: list[dict] | None = None) -> dict:
    return {"state": state, "items": items or []}


def _stock_items(db: Session, picked: list[tuple[str, str]], words: dict, now: datetime) -> list[dict]:
    """저장소에 그림이 있는 오늘 단어를 추천 항목으로 만든다(단어마다 가장 최근 그림)."""
    items = []
    for word, source in picked:
        variants = draw_stock.stock_variants(db, word, now)
        if variants:
            items.append(
                {
                    "id": variants[-1].id,
                    "source": source,
                    "word": word,
                    "alt_answers": list(words[word].alts),
                    "strokes": variants[-1].strokes,
                }
            )
    return items


def recommend(db: Session, user: User, group_id: str, rng: random.Random | None = None) -> dict:
    """오늘의 이게 뭐게 가비 추천을 돌려준다: {"state": ..., "items": [{id, source, word, alt_answers, strokes}]}.
    오류는 상태로 바꿔 돌려준다. 하루 한 번 만들어 가족이 오늘 자정까지 같이 쓴다(5개가 다 모이면 캐시한다. 모자라면 캐시하지 않고, 저장소에 있는 오늘 단어의 그림을 `partial` 로 보여 주며 다음에 한도 안에서 더 채운다. 한도를 다 쓰면 저장소 그림을 그대로 `ok` 로 보여 준다)."""
    now = datetime.now(UTC)
    today = now.astimezone(local_tz()).date()
    rng = rng or daily_rng(group_id, today)
    recent = recent_words(db, group_id, now)
    words = draw_words.load_words()

    picks: list[list[tuple[str, str]]] = []  # 오늘 뽑은 단어(시도에서 뽑았으면 그대로, 못 뽑았으면 아래에서 같은 난수로 다시 뽑는다)

    def picked_words():
        if not picks:
            picks.append(pick_words(family_words(db, group_id, today, now), recent, rng))
        return picks[0]

    def call():
        picked = picked_words()
        chosen: dict[str, object] = {}
        to_draw: list[str] = []
        for word, _source in picked:
            variants = draw_stock.stock_variants(db, word, now)
            if variants and rng.random() >= REDRAW_RATE:
                chosen[word] = rng.choice(variants)
            else:
                to_draw.append(word)
        tokens_in = tokens_out = 0
        model = None
        drawn: dict[str, list] = {}
        if to_draw:
            with ThreadPoolExecutor(
                max_workers=len(to_draw)
            ) as pool:  # 그림을 동시에 부른다(DB 는 이 스레드에서만 쓴다)
                futures = {word: pool.submit(draw_word, word) for word in to_draw}
                for word, future in futures.items():
                    try:
                        strokes, usage = future.result()
                    except DrawFailed as failed:
                        tokens_in += failed.input_tokens
                        tokens_out += failed.output_tokens
                    except llm.LLMUnavailable:
                        pass
                    else:
                        tokens_in += usage.input_tokens
                        tokens_out += usage.output_tokens
                        model = usage.model
                        drawn[word] = strokes
        for word, strokes in drawn.items():
            chosen[word] = draw_stock.add_variant(db, word, strokes, now)
        items = [
            {
                "id": chosen[word].id,
                "source": source,
                "word": word,
                "alt_answers": list(words[word].alts),
                "strokes": chosen[word].strokes,
            }
            for word, source in picked
            if word in chosen
        ]
        if len(items) < len(picked):  # 5개가 안 된다 — 만든 그림은 저장소에 남고, 캐시하지 않아 다음에 더 채운다(시도 1회로 센다)
            raise DrawFailed("만든 그림이 모자라요", 1, tokens_in, tokens_out)  # 한도에는 시도 1회
        return {"items": items}, _Batch(model or settings.llm_model, tokens_in, tokens_out)

    try:
        outcome = ai_guard.run(
            db,
            user_id=user.id,
            group_id=group_id,
            feature=FEATURE,
            cache_key=_cache_key(today),
            call=call,
            cache_until=local_day_start(now) + timedelta(days=1),
        )
    except ApiError as error:
        state = quiz_rec._state_of(error)
        if state == quiz_rec.AI_OFF:
            return _reply(state)
        shown = [i for i in _stock_items(db, picked_words(), words, now) if _norm(i["word"]) not in recent]
        if not shown:
            return _reply(state)
        # 저장소에 오늘 단어의 그림이 있으면 보여 준다. 한도를 다 쓴 때는 더 할 게 없으니 ok, 그 밖에는 다시 불러 더 채울 수 있다
        return _reply(quiz_rec.OK if state == quiz_rec.USED_UP else PARTIAL, shown)
    items = [i for i in outcome.result.get("items", []) if _norm(i["word"]) not in recent]
    return _reply(quiz_rec.OK, items) if items else _reply(quiz_rec.USED_UP)
