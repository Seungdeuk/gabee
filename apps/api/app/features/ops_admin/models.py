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
