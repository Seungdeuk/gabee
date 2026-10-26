import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy.orm import Session

from app.shared.errors import ApiError, bad_request, not_found

from . import repository as repo
from .models import Event
from .schemas import EventCreate, EventUpdate
from .timeutil import local_tz


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _when(body: EventCreate) -> tuple[datetime, date, time | None, time | None]:
    """(starts_at, start_date, start_time, end_time). 옛 컬럼 starts_at 도 계속 채운다."""
    tz = local_tz()
    if body.start_date is not None:
        starts_at = datetime.combine(body.start_date, body.start_time or time(0, 0), tzinfo=tz)
        return starts_at.astimezone(UTC), body.start_date, body.start_time, body.end_time
    starts_at = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=UTC)
    local = starts_at.astimezone(tz)
    return starts_at, local.date(), local.time().replace(second=0, microsecond=0), body.end_time


def _share_targets(db: Session, group_id: str, user_id: str, share_with: list[str]) -> list[str]:
    """복사본을 받을 사람들(나와 중복은 뺀다). 같은 가족 구성원이 아닌 사람이 있으면 거절한다."""
    wanted = [u for u in dict.fromkeys(share_with) if u != user_id]
    if wanted and set(wanted) - repo.member_ids(db, group_id, wanted):
        raise bad_request("invalid_share_target", "같은 가족 구성원이 아닌 사람이 있어요")
    return wanted


def create(db: Session, group_id: str, user_id: str, body: EventCreate) -> Event:
    """내 일정 한 줄을 만들고, 공유 대상마다 그 사람 몫의 복사본을 만든다.
    복사본은 만들어진 뒤로는 그 사람의 일정이라 원본을 고치거나 지워도 그대로다(`origin_id` 로 출처만 남긴다)."""
    starts_at, start_date, start_time, end_time = _when(body)
    memo = body.memo if body.memo is not None else body.note
    targets = _share_targets(db, group_id, user_id, body.share_with)
    fields = dict(
        group_id=group_id,
        created_by=user_id,
        title=body.title.strip(),
        starts_at=starts_at,
        note=memo,
        memo=memo,
        status=body.status,
        source=body.source,
        kind=body.kind,
        place=body.place.strip(),
        who_ids=list(dict.fromkeys(body.who_ids)),
        start_date=start_date,
        start_time=start_time,
        end_time=end_time,
    )
    original = Event(id=_new_id(), user_id=user_id, **fields)
    copies = [Event(id=_new_id(), user_id=t, origin_id=original.id, **fields) for t in targets]
    repo.add_all(db, [original, *copies])
    return original


def upcoming(db: Session, group_id: str, user_id: str, include_past: bool = False) -> list[Event]:
    return repo.list_from(db, group_id, None if include_past else datetime.now(UTC), user_id)


def confirm(db: Session, group_id: str, user_id: str, event_id: str) -> Event:
    event = repo.get(db, group_id, event_id, user_id)
    if event is None:
        raise not_found("일정")
    event.status = "confirmed"
    db.commit()
    return event


def owns(event: Event, user_id: str) -> bool:
    """그 줄의 주인인가. 주인이 없던 옛 줄은 만든 사람이 주인이다."""
    return event.user_id == user_id or (event.user_id is None and event.created_by == user_id)


def update(db: Session, group_id: str, user_id: str, event_id: str, body: EventUpdate) -> Event:
    """내 줄의 값을 고친다. 복사본은 그 사람의 일정이라 원본을 고쳐도 번지지 않고, 복사본은 받은 사람이 자기 줄에서 고친다.
    옛 컬럼(starts_at, note)도 함께 맞추고 고친 시각(edited_at)을 남긴다."""
    event = repo.get(db, group_id, event_id, user_id)
    if event is None:
        raise not_found("일정")
    if not owns(event, user_id):
        raise ApiError(403, "not_owner", "내 일정만 고칠 수 있어요")
    sent = body.model_fields_set
    if not sent:
        raise bad_request("nothing_to_update", "바꿀 값이 없어요")

    if body.title is not None:
        event.title = body.title.strip()
    if body.kind is not None:
        event.kind = body.kind
    if body.place is not None:
        event.place = body.place.strip()
    if body.memo is not None:
        event.memo = body.memo
        event.note = body.memo
    if body.who_ids is not None:
        event.who_ids = list(dict.fromkeys(body.who_ids))

    if sent & {"start_date", "start_time", "end_time"}:
        _apply_when(event, body, sent)
    event.edited_at = datetime.now(UTC)
    db.commit()
    return event


def current_when(event: Event) -> tuple[date, time | None, time | None]:
    """지금 저장된 (날짜, 시작 시간, 끝 시간). 새 구조 이전에 만든 옛 일정은 시각에서 날짜·시작 시간을 읽는다."""
    if event.start_date is None:
        local = event.starts_at.replace(tzinfo=event.starts_at.tzinfo or UTC).astimezone(local_tz())
        return local.date(), local.time().replace(second=0, microsecond=0), event.end_time
    return event.start_date, event.start_time, event.end_time


def resolve_when(
    event: Event, body: EventUpdate, sent: set[str]
) -> tuple[date, time | None, time | None]:
    """고친 뒤의 (날짜, 시작 시간, 끝 시간)을 계산한다(저장하지 않는다). 보내지 않은 값은 그대로 두고,
    시작 시간이 없어지면 끝 시간도 없앤다(시간 없음). 끝이 시작보다 늦지 않으면 400."""
    base_date, base_start, base_end = current_when(event)
    start_date = body.start_date or base_date
    start_time = body.start_time if "start_time" in sent else base_start
    end_time = body.end_time if "end_time" in sent else base_end
    if start_time is None:
        end_time = None
    if start_time and end_time and end_time <= start_time:
        raise bad_request("invalid_time", "끝나는 시간은 시작하는 시간보다 늦어야 해요")
    return start_date, start_time, end_time


def _apply_when(event: Event, body: EventUpdate, sent: set[str]) -> None:
    """날짜·시간을 고친다."""
    tz = local_tz()
    start_date, start_time, end_time = resolve_when(event, body, sent)
    event.start_date = start_date
    event.start_time = start_time
    event.end_time = end_time
    event.starts_at = datetime.combine(start_date, start_time or time(0, 0), tzinfo=tz).astimezone(
        UTC
    )


def remove(db: Session, group_id: str, user_id: str, event_id: str) -> None:
    """내 줄만 지운다(소프트 삭제). 원본을 지워도 복사본은 그대로고, 복사본은 받은 사람이 지운다."""
    event = repo.get(db, group_id, event_id, user_id)
    if event is None:
        raise not_found("일정")
    if not owns(event, user_id):
        raise ApiError(403, "not_owner", "내 일정만 지울 수 있어요")
    repo.soft_delete(db, event)
