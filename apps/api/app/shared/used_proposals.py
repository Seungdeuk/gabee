"""에이전트 쓰기 제안 토큰의 사용 기록(한 번만 쓰게 하려는 표시).

여러 서버 인스턴스(Cloud Run)나 재시작에도 같은 토큰을 두 번 실행하지 못하게 PostgreSQL 에 둔다.
토큰 원문은 저장하지 않고 토큰 안의 jti(무작위 ID)와 만료 시각만 남기며, 만료가 지난 행은 새 토큰을 쓸 때 지운다."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class AgentProposalUse(Base):
    __tablename__ = "agent_proposal_uses"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
