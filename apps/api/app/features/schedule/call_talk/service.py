"""전화 이야깃거리: 대상 가족의 오늘 공개 습관으로 AI 문구 한 쌍을 만든다. 만들 수 없으면 안부 문구로 돌려준다.

- 사용자에게 오류를 내지 않는다(대상이 같은 가족이 아니면 404 만). 동의 꺼짐·한도·호출 실패는 모두 안부 문구 + reason 이다.
- 호출은 공통 관문 `ai_guard.run` 을 거친다. 캐시 키가 (대상, 한국 날짜, 습관 줄 전체)라서 상대 상태가 같으면 저장된 문구를 다시 쓰고 한도를 쓰지 않는다.
- 가족 호칭·이름은 모델에 보내지 않는다. 습관 이름은 개인정보를 가려 보낸다.
"""

import hashlib
import random
import re

from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm import client as llm

from .. import check as check_service
from ..constants import CHECK_KIND_CHECK, SUGGEST_GREETING
from ..suggestion import repository as suggestions
from ..timeutil import local_tz
from . import prompts

FEATURE = "schedule_call_talk"
MAX_LINES = 20
MAX_CHARS = 40  # 프롬프트는 30자 이내를 요구하지만 서버 검증은 40자까지 허용한다
GREETING_MAX = 2

# 줄이거나 참는 습관 표시(평가에서 확정한 정규식). 오탐이 있어도 문구가 안부로 돌아갈 뿐이라 안전하다.
AVOID_WORDS = re.compile(
    r"(^금|안 ?(먹|마시|피우|보|하)기|끊기|참기|줄이기|이하|만 ?(하|보|먹|마시)기|한 ?잔만|덜 )"
)


def register() -> None:
    ai_guard.register_bucket(
        FEATURE,
        ai_guard.Limits(
            settings.ai_call_talk_cooldown_seconds,
            settings.ai_call_talk_max_calls_per_user_per_day,
            settings.ai_call_talk_max_calls_per_group_per_day,
        ),
        (FEATURE,),
    )


register()


def is_avoid(name: str) -> bool:
    return bool(AVOID_WORDS.search(name))


def _state(item: dict) -> str:
    if item["kind"] == CHECK_KIND_CHECK:
        if not item["done"]:
            return "아직"
        at = item["confirmed_at"]
        return f"완료({at.astimezone(local_tz()):%H:%M})" if at else "완료"
    return f"{item['count'] or 0}/{item['goal'] or 0}{item['unit']}"


def habit_lines(items: list[dict]) -> list[str]:
    lines = []
    for item in items[:MAX_LINES]:
        tag = " [줄이는 습관]" if is_avoid(item["name"]) else ""
        lines.append(f"- {mask_text(item['name'])}{tag}: {_state(item)}")
    return lines


def _clean(value) -> str:
    if not isinstance(value, str):
        raise ValueError("문구가 문자열이 아니에요")
    text = " ".join(value.replace('"', "").replace("'", "").split())
    if not text or len(text) > MAX_CHARS:
        raise ValueError("문구 길이가 맞지 않아요")
    return text


def clean_pair(data) -> dict:
    """모델 출력을 믿지 않고 검증한다: say·ask 모두 비어 있지 않고 40자 이하여야 한다. 어기면 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("형식이 올바르지 않아요")
    return {"say": _clean(data.get("say")), "ask": _clean(data.get("ask"))}


def _greeting(db: Session, reason: str) -> dict:
    rows = suggestions.random_active(db, SUGGEST_GREETING, random.randint(1, GREETING_MAX))
    return {
        "source": "greeting",
        "reason": reason,
        "points": [{"say": r.content, "ask": ""} for r in rows],
    }


def _reason_of(exc: ApiError) -> str:
    if exc.code == "ai_not_enabled":
        return "no_consent"
    if exc.code in ("ai_daily_limit_user", "ai_daily_limit_group", "ai_cooldown"):
        return "limit"
    return "error"  # 동시 실행 제한(ai_busy)·서버 미설정·호출 실패 등


def call_talk(db: Session, user_id: str, group_id: str, target_id: str) -> dict:
    today = check_service.member_today(db, group_id, target_id)  # 같은 가족이 아니면 404
    lines = habit_lines(today["items"])
    if not lines:
        return _greeting(db, "no_habits")
    prompt = "오늘 데일리 체크\n" + "\n".join(lines)
    day = check_service.today_of(check_service.now_utc())
    key = hashlib.sha256(f"{target_id}\n{day}\n{prompt}".encode()).hexdigest()

    def call() -> tuple[dict, llm.JsonResult]:
        response = llm.complete_json(
            prompt, prompts.SCHEMA, system=prompts.SYSTEM, max_tokens=300, model=prompts.MODEL
        )
        return clean_pair(response.data), response  # 검증에 실패한 결과는 캐시에 저장하지 않는다

    try:
        outcome = ai_guard.run(
            db,
            user_id=user_id,
            group_id=group_id,
            feature=FEATURE,
            cache_key=key,
            call=call,
        )
        pair = clean_pair(outcome.result)
    except ApiError as exc:
        return _greeting(db, _reason_of(exc))
    except ValueError:
        return _greeting(db, "error")
    return {"source": "ai", "reason": "", "points": [pair]}
