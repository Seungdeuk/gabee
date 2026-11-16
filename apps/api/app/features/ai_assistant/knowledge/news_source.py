"""주간 가족 뉴스의 문서함 재료를 읽는다(`shared/weekly_sources.py` 에 등록, ai_assistant/router 가 import 하면 등록된다).

그 가족의 문서함 기록 중 민감하지 않고(`sensitivity != "sensitive"`) 만든 날(`created_at`, 서비스 시간대 달력 날짜)이 그 주 안인 것의
**종류 라벨·날짜만** 낸다(2026-11-11 사용자 결정: 제목은 보내지 않는다). 제목·본문(`body_md`)·조각·가린 글은 읽지도 않는다. 문서함은 가족 공유라 올린 사람과 상관없이 같은 가족이면
같은 재료다. 제목 속 `[가족:<id>]` 는 현재 이름으로 되돌린다(`family_names.restore`: 나간 사람·모르는 id 는 '가족 구성원').
제목을 읽지 않으므로 제목 속 실명·진단서 같은 정보는 재료에 들어오지 않는다. 라벨 자체가 민감 주제어면 수집기(`weekly_sources.collect`)가 뺀다."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared import weekly_sources
from app.shared.config import settings
from app.shared.weekly_sources import SourceRecord

from . import service
from .models import KnowledgeItem

_MAX_ROWS = 500  # 한 주에 이보다 많이 올린 가족도 메모리를 지키려고 앞(이른 날짜)에서 자른다. 뉴스 입력 상한은 수집기가 따로 건다.


def _local_day(created: datetime, offset_hours: int) -> date:
    """저장된 UTC 시각의 서비스 시간대 달력 날짜. SQLite 는 시간대를 지우고 돌려주므로 UTC 로 본다(PostgreSQL 은 aware)."""
    utc = created if created.tzinfo else created.replace(tzinfo=UTC)
    return (utc.astimezone(UTC) + timedelta(hours=offset_hours)).date()


def week_documents(
    db: Session, group_id: str, user_id: str, start: date, end: date
) -> list[SourceRecord]:
    """그 가족의 그 주 문서함 기록(종류 라벨·제목·날짜만). user_id 는 쓰지 않는다(가족 공유)."""
    offset = settings.ai_day_utc_offset_hours
    created_from, created_to = service.created_bounds(start, end, offset)
    rows = db.execute(
        select(
            KnowledgeItem.id,
            KnowledgeItem.kind_label,
            KnowledgeItem.created_at,
        )
        .where(
            KnowledgeItem.group_id == group_id,
            KnowledgeItem.sensitivity != "sensitive",
            KnowledgeItem.created_at >= created_from,
            KnowledgeItem.created_at < created_to,
        )
        .order_by(KnowledgeItem.created_at, KnowledgeItem.id)
        .limit(_MAX_ROWS)
    ).all()
    return [
        SourceRecord(
            kind="document",
            ref=item_id,
            title=label,  # 종류 라벨만(제목은 읽지 않는다)
            day=_local_day(created, offset),
        )
        for item_id, label, created in rows
    ]


weekly_sources.register_provider(weekly_sources.DOCUMENTS, "ai_assistant", week_documents)
