"""운영 관리자 페이지(ops_admin)의 테이블.

`ops_request_metrics`: 요청을 건별로 남기지 않고 시간 구간(기본 5분)·메서드·경로 패턴·상태코드 구분별로 합친 집계다.
URL 원문, 본문, 쿼리, 헤더, 사용자·가족 id 는 이 테이블에 들어갈 자리가 없다(컬럼 자체가 없다).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class OpsRequestMetric(Base):
    __tablename__ = "ops_request_metrics"
    __table_args__ = (Index("ix_ops_request_metrics_bucket", "bucket_start"),)

    # 한 구간의 같은 (메서드, 경로 패턴, 상태코드 구분)은 한 행이고, 인스턴스가 여러 개여도 같은 행에 더해진다.
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    method: Mapped[str] = mapped_column(String(8), primary_key=True)
    route: Mapped[str] = mapped_column(
        String(200), primary_key=True
    )  # 경로 패턴(`/items/{id}`) 또는 unmatched
    status_class: Mapped[str] = mapped_column(String(3), primary_key=True)  # 2xx 3xx 4xx 5xx
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms_sum: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms_max: Mapped[float] = mapped_column(Float, default=0.0)


class OpsErrorEvent(Base):
    """서버 오류·인증 실패를 지문(fingerprint)별로 합친 기록. 같은 오류는 한 행에 횟수만 올라간다.

    사용자·가족 id, URL 원문, 요청 본문·헤더, 스택의 변수 값을 담는 컬럼이 없다. 메시지는 가린 뒤 200자까지만 저장하고,
    인증 실패(401/403)는 메시지를 저장하지 않고 응답의 code 만 event_type 에 둔다.
    """

    __tablename__ = "ops_error_events"
    __table_args__ = (Index("ix_ops_error_events_last_seen", "last_seen"),)

    # sha256(kind|event_type|route|status|가린 메시지)
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # server_error | auth_failure
    severity: Mapped[str] = mapped_column(String(8))  # error | warning
    event_type: Mapped[str] = mapped_column(String(100))  # 예외 클래스 이름 또는 오류 code
    method: Mapped[str] = mapped_column(String(8))
    route: Mapped[str] = mapped_column(String(200))  # 경로 패턴 또는 unmatched
    status: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(200), default="")  # 가린 메시지
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)  # app/...py:줄
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 2단계(처리 상태 변경)에서 쓴다. 지금은 채우지 않는다
    handling_status: Mapped[str] = mapped_column(String(16), default="new")
    assignee_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # 운영자 id 가 아니라 라벨
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
