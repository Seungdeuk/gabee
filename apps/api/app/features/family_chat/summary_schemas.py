"""가족 채팅 대화 요약(AI)의 요청·응답 모델."""

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryIn(BaseModel):
    """요약할 범위. after_id 를 주면 그 뒤의 대화, 아니면 최근 limit 개(둘 다 주면 after_id 뒤의 최근 limit 개)."""

    limit: int = Field(default=200, ge=1, le=300)
    after_id: int = Field(default=0, ge=0)


class SummaryOut(BaseModel):
    summary: str
    message_count: int  # 요약에 쓴 메시지 수(글자 수 한도 때문에 오래된 것이 빠졌을 수 있다)
    from_message_id: int
    to_message_id: int
    model: str  # 요약에 쓴 모델 이름(ANTHROPIC_MODEL)
    generated_at: datetime
