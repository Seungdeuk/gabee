"""ops_request_metrics 접근. 업무 규칙은 service.py 에 있고 여기서는 DB 만 다룬다."""

from datetime import datetime

from sqlalchemy import delete, func
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from .models import OpsRequestMetric

# 행 = (bucket_start, method, route, status_class, count, duration_sum, duration_max)
Row = tuple[datetime, str, str, str, int, float, float]


def upsert_rows(db: Session, rows: list[Row]) -> None:
    """집계 행을 저장한다. 같은 키가 이미 있으면(다른 인스턴스·같은 구간의 이전 저장) 더하고 최댓값은 큰 쪽을 둔다."""
    if not rows:
        return
    dialect = db.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    # 두 값 중 큰 쪽: PostgreSQL 은 GREATEST, SQLite 는 인자가 둘인 max
    biggest = func.greatest if dialect == "postgresql" else func.max
    for bucket_start, method, route, status_class, count, total, peak in rows:
        stmt = insert(OpsRequestMetric).values(
            bucket_start=bucket_start,
            method=method,
            route=route,
            status_class=status_class,
            request_count=count,
            duration_ms_sum=total,
            duration_ms_max=peak,
        )
        table = OpsRequestMetric.__table__
        stmt = stmt.on_conflict_do_update(
            index_elements=["bucket_start", "method", "route", "status_class"],
            set_={
                "request_count": table.c.request_count + stmt.excluded.request_count,
                "duration_ms_sum": table.c.duration_ms_sum + stmt.excluded.duration_ms_sum,
                "duration_ms_max": biggest(table.c.duration_ms_max, stmt.excluded.duration_ms_max),
            },
        )
        db.execute(stmt)
    db.commit()


def delete_before(db: Session, cutoff: datetime) -> int:
    """cutoff 보다 오래된 구간을 지우고 지운 행 수를 돌려준다."""
    result = db.execute(delete(OpsRequestMetric).where(OpsRequestMetric.bucket_start < cutoff))
    db.commit()
    return result.rowcount or 0
