"""일정 에이전트의 AI 호출 한도. 기본 한도(채팅 분석 등)와 따로 센다: 채팅과 카드 공급도 서로 따로 센다."""

from app.shared import ai_guard
from app.shared.config import settings

CHAT_FEATURES = ("schedule_chat",)
CARD_FEATURES = ("schedule_card",)


def register() -> None:
    ai_guard.register_bucket(
        "schedule_chat",
        ai_guard.Limits(
            settings.ai_schedule_chat_cooldown_seconds,
            settings.ai_schedule_chat_max_calls_per_user_per_day,
            settings.ai_schedule_chat_max_calls_per_group_per_day,
        ),
        CHAT_FEATURES,
    )
    ai_guard.register_bucket(
        "schedule_card",
        ai_guard.Limits(
            settings.ai_schedule_card_cooldown_seconds,
            settings.ai_schedule_card_max_calls_per_user_per_day,
            settings.ai_schedule_card_max_calls_per_group_per_day,
        ),
        CARD_FEATURES,
    )


register()
