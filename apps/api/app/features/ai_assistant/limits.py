"""AI 어시스턴트(채팅·기록 질문)의 AI 호출 한도. 가족 채팅 AI 의 기본 한도와 따로 센다(ai_guard.register_bucket).
이 기능이 예전에 쓰던 값(사용자 100회/일, 쿨다운 없음)을 그대로 쓴다. 질문 1건이 도구 루프로 최대 4번 부르면 모두 센다."""

from app.shared import ai_guard
from app.shared.config import settings

ASSISTANT_FEATURES = ("assistant_chat", "knowledge_ask")


def register() -> None:
    ai_guard.register_bucket(
        "assistant",
        ai_guard.Limits(
            settings.ai_assistant_cooldown_seconds,
            settings.ai_assistant_max_calls_per_user_per_day,
            settings.ai_assistant_max_calls_per_group_per_day,
        ),
        ASSISTANT_FEATURES,
    )


register()
