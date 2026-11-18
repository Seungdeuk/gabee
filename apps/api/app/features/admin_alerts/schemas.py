"""관리자 알림 주소의 입출력 모양. 개인 정보 칸은 없다."""

from datetime import datetime

from pydantic import BaseModel


class AlertItemOut(BaseModel):
    key: str
    rule: str
    severity: str  # 긴급 | 주의 | 보통
    message: str  # 숫자만 든 문구
    menu: str  # 확인할 메뉴 이름
    created_at: datetime
    acked_at: datetime | None


class AlertListOut(BaseModel):
    items: list[AlertItemOut]
    unacked: int  # 확인 안 된 알림 개수(배지용)


class RunOut(BaseModel):
    enabled: bool  # 설정이 꺼져 있으면 false 이고 아무 일도 하지 않았다
    checked: int  # 점검한 규칙 수
    created: int  # 이번 점검으로 새로 만든 알림 수
