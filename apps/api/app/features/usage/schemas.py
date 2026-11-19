from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Tab = Literal["chat", "family-chat", "schedule", "care", "my", "other"]
Seconds = Annotated[int, Field(ge=0, le=24 * 60 * 60)]

SESSION_MAX_SECONDS = 4 * 60 * 60  # 한 번 보내는 값의 탭별 상한(켜 둔 채 잠든 경우 등)


class UsageReportIn(BaseModel):
    """앱이 백그라운드로 갈 때 한 번 보내는 사용 기록. 탭별 초와 그동안의 실행 횟수만 담는다."""

    day: date  # 사용한 날(기기 날짜)
    opens: int = Field(default=0, ge=0, le=20)
    tabs: dict[Tab, Seconds] = Field(max_length=6)  # 탭 이름 → 초

    def clean_tabs(self) -> dict[str, int]:
        """0 초는 빼고, 한 번에 너무 큰 값은 상한(4시간)으로 자른다."""
        return {tab: min(sec, SESSION_MAX_SECONDS) for tab, sec in self.tabs.items() if sec > 0}
