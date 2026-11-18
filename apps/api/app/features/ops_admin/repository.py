"""ops_request_metrics 접근. 업무 규칙은 service.py 에 있고 여기서는 DB 만 다룬다."""

from datetime import datetime

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, aliased

from .models import OpsErrorEvent, OpsRequestMetric

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


def totals_by_bucket(db: Session, since: datetime) -> list[tuple[datetime, str, int, float, float]]:
    """since 이후의 (구간 시작, 상태코드 구분)별 요청 수·걸린 시간 합·최댓값."""
    stmt = (
        select(
            OpsRequestMetric.bucket_start,
            OpsRequestMetric.status_class,
            func.sum(OpsRequestMetric.request_count),
            func.sum(OpsRequestMetric.duration_ms_sum),
            func.max(OpsRequestMetric.duration_ms_max),
        )
        .where(OpsRequestMetric.bucket_start >= since)
        .group_by(OpsRequestMetric.bucket_start, OpsRequestMetric.status_class)
    )
    return [(b, s, int(c), float(t), float(m)) for b, s, c, t, m in db.execute(stmt)]


def totals_by_route(db: Session, since: datetime) -> list[tuple[str, str, str, int, float, float]]:
    """since 이후의 (메서드, 경로 패턴, 상태코드 구분)별 요청 수·걸린 시간 합·최댓값."""
    stmt = (
        select(
            OpsRequestMetric.method,
            OpsRequestMetric.route,
            OpsRequestMetric.status_class,
            func.sum(OpsRequestMetric.request_count),
            func.sum(OpsRequestMetric.duration_ms_sum),
            func.max(OpsRequestMetric.duration_ms_max),
        )
        .where(OpsRequestMetric.bucket_start >= since)
        .group_by(OpsRequestMetric.method, OpsRequestMetric.route, OpsRequestMetric.status_class)
    )
    return [(m, r, s, int(c), float(t), float(p)) for m, r, s, c, t, p in db.execute(stmt)]


def upsert_error_event(
    db: Session,
    *,
    fingerprint: str,
    kind: str,
    severity: str,
    event_type: str,
    method: str,
    route: str,
    status: int,
    message: str,
    location: str | None,
    trace_id: str | None,
    now: datetime,
) -> None:
    """오류 이벤트를 저장한다. 같은 지문이 있으면 횟수를 올리고 마지막 발생 시각·trace id 만 갱신한다."""
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    stmt = insert(OpsErrorEvent).values(
        fingerprint=fingerprint,
        kind=kind,
        severity=severity,
        event_type=event_type,
        method=method,
        route=route,
        status=status,
        message=message,
        location=location,
        occurrences=1,
        first_seen=now,
        last_seen=now,
        last_trace_id=trace_id,
        handling_status="new",
    )
    table = OpsErrorEvent.__table__
    stmt = stmt.on_conflict_do_update(
        index_elements=["fingerprint"],
        set_={
            "occurrences": table.c.occurrences + 1,
            "last_seen": stmt.excluded.last_seen,
            "last_trace_id": stmt.excluded.last_trace_id,
        },
    )
    db.execute(stmt)
    db.commit()


def delete_error_events_before(db: Session, cutoff: datetime) -> int:
    """마지막 발생이 cutoff 보다 오래된 오류 이벤트를 지우고 지운 행 수를 돌려준다."""
    result = db.execute(delete(OpsErrorEvent).where(OpsErrorEvent.last_seen < cutoff))
    db.commit()
    return result.rowcount or 0


def list_error_events(
    db: Session, since: datetime, kind: str | None, limit: int
) -> tuple[int, list[OpsErrorEvent]]:
    """since 이후에 마지막으로 발생한 오류 이벤트를 최근순으로. (조건에 맞는 전체 수, limit 개까지의 목록)."""
    where = [OpsErrorEvent.last_seen >= since]
    if kind:
        where.append(OpsErrorEvent.kind == kind)
    total = db.scalar(select(func.count()).select_from(OpsErrorEvent).where(*where)) or 0
    stmt = (
        select(OpsErrorEvent)
        .where(*where)
        .order_by(OpsErrorEvent.last_seen.desc(), OpsErrorEvent.fingerprint)
        .limit(limit)
    )
    return int(total), list(db.scalars(stmt))


def get_error_event(db: Session, fingerprint: str) -> OpsErrorEvent | None:
    return db.get(OpsErrorEvent, fingerprint)


def new_server_error_pairs(
    db: Session, since: datetime, limit: int
) -> list[tuple[str, str, int, datetime]]:
    """since 이후 처음 나온 서버 오류의 (오류 종류, 경로) 조합. 횟수가 많은 것 먼저, 최대 limit 개.

    지문(fingerprint)에는 가린 메시지가 섞여 있어서 같은 종류·같은 경로여도 메시지가 다르면 줄이 따로 생긴다.
    그래서 줄이 아니라 (종류, 경로) 조합으로 묶고, since 이전에 같은 조합이 한 번이라도 있었으면 새것으로 보지 않는다.
    행 = (event_type, route, 횟수 합, 처음 본 시각).
    """
    older = aliased(OpsErrorEvent)
    already_seen = exists().where(
        older.kind == "server_error",
        older.event_type == OpsErrorEvent.event_type,
        older.route == OpsErrorEvent.route,
        older.first_seen < since,
    )
    total = func.sum(OpsErrorEvent.occurrences)
    stmt = (
        select(
            OpsErrorEvent.event_type,
            OpsErrorEvent.route,
            total,
            func.min(OpsErrorEvent.first_seen),
        )
        .where(
            OpsErrorEvent.kind == "server_error",
            OpsErrorEvent.first_seen >= since,
            ~already_seen,
        )
        .group_by(OpsErrorEvent.event_type, OpsErrorEvent.route)
        .order_by(total.desc(), OpsErrorEvent.event_type, OpsErrorEvent.route)
        .limit(limit)
    )
    return [(t, r, int(n), first) for t, r, n, first in db.execute(stmt)]
