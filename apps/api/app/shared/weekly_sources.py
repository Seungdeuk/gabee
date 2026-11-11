"""주간 가족 뉴스의 재료를 모으는 통로. weekly_news 가 일정·문서함 같은 다른 기능의 데이터를 직접 읽지 않도록,
데이터 주인 기능(schedule·ai_assistant)이 시작할 때 **재료를 읽는 함수**를 여기에 등록하고, weekly_news 는 `collect` 만 부른다
(`shared/chat_share.py`·`shared/chat_library.py` 와 같은 방향). `SourceRecord` 도 기능 폴더가 아니라 여기에 둔다.

- 재료 하나(일정·문서)가 읽히지 않아도 나머지로 뉴스를 만든다: 제공자가 등록되지 않았거나, 주인 기능의 표가 준비되지 않았거나
  (`monitor.status().feature_ready`), 읽다가 예외가 나면 그 재료의 이름만 `unavailable` 에 넣는다. 예외는 종류(클래스 이름)만 기록한다.
- 입력 상한(약속 30·할 일 30·문서 20): 날짜·시간 순으로 앞에서 자르고 `truncated=True` 로 알린다.
- `collect` 를 부르는 쪽은 `group_id`·`user_id` 가 실제 구성원 관계인지 먼저 확인해야 한다(`ensure_group_member`).
  제공자는 받은 값으로 자기 기능의 데이터를 읽을 뿐 구성원 여부는 다시 확인하지 않는다.
- **계약(호출 순서)**: 제공자가 실패하면 `collect` 가 `db.rollback()` 을 부른다. 그러니 커밋하지 않은 쓰기(예: 만드는 중인
  pending 줄)가 있는 세션으로 `collect` 를 부르지 말고, **`collect` 를 먼저 하고 그 뒤에 쓰기·커밋**한다(T26-b 호출 순서).
  세이브포인트로 바꾸지 않은 것은 SQLite·PostgreSQL 동작 차이 위험 때문이다."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.shared.schema import monitor

logger = logging.getLogger(__name__)

SCHEDULE = "schedule"  # 약속(event)·완료한 할 일(todo)
DOCUMENTS = "documents"  # 문서함 기록(document)
EXPECTED = (SCHEDULE, DOCUMENTS)  # 등록돼 있어야 하는 재료. 없으면 unavailable

# 종류별 입력 상한(모듈 상수)
LIMITS = {"event": 30, "todo": 30, "document": 20}


@dataclass(frozen=True)
class SourceRecord:
    """근거 목록의 재료 한 건. 제목·날짜·시각 말고는 받지 않는다."""

    kind: str  # "event" | "todo" | "document"
    ref: str  # 원본 기록 id(일정·문서). 화면 이동에 쓴다
    title: str
    day: date
    start_time: str | None = None  # "HH:MM"


@dataclass
class Collected:
    records: list[SourceRecord] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)  # 읽지 못한 재료 이름
    truncated: bool = False  # 상한을 넘어 잘렸는가


# (db, group_id, user_id, start, end) → 그 주(양끝 포함)의 재료
Provider = Callable[[Session, str, str, date, date], list[SourceRecord]]
_providers: dict[str, tuple[str, Provider]] = {}  # 재료 이름 → (주인 기능, 읽는 함수)


def register_provider(name: str, owner_feature: str, fn: Provider) -> None:
    """name 재료를 읽는 함수를 등록한다(주인 기능이 시작할 때 부른다). owner_feature 는 표 준비 확인에 쓴다."""
    _providers[name] = (owner_feature, fn)


def _read(db: Session, name: str, args: tuple) -> list[SourceRecord] | None:
    """제공자 하나를 읽는다. 쓸 수 없으면 None. 예외가 나면 세션 전체를 `rollback()` 하므로(계약은 모듈 설명)
    커밋하지 않은 쓰기가 있는 세션으로 부르면 안 된다."""
    entry = _providers.get(name)
    if entry is None or not monitor.status().feature_ready(entry[0]):
        return None
    try:
        return list(entry[1](db, *args))
    except Exception as exc:  # noqa: BLE001  재료 하나가 뉴스 전체를 막으면 안 된다(종류만 기록)
        db.rollback()
        logger.warning("weekly source failed name=%s error=%s", name, type(exc).__name__)
        return None


def _order(r: SourceRecord) -> tuple:
    return (r.day, r.start_time or "", r.ref)


def collect(db: Session, group_id: str, user_id: str, start: date, end: date) -> Collected:
    """그 구성원의 그 주(start~end 양끝 포함) 재료를 모은다. 날짜·시간 순이고 종류별 상한을 넘으면 앞에서 자른다.

    제공자 실패 시 `db.rollback()` 을 부르므로, 커밋하지 않은 쓰기가 있는 세션으로 부르지 말고 `collect` 를 먼저 한 뒤 쓰기·커밋한다."""
    out = Collected()
    found: list[SourceRecord] = []
    for name in dict.fromkeys([*EXPECTED, *_providers]):
        records = _read(db, name, (group_id, user_id, start, end))
        if records is None:
            out.unavailable.append(name)
        else:
            found += records
    for kind, limit in LIMITS.items():
        mine = sorted((r for r in found if r.kind == kind), key=_order)
        out.truncated = out.truncated or len(mine) > limit
        out.records += mine[:limit]
    out.records.sort(key=_order)
    return out
