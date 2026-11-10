"""채팅방 공유 카드의 일정 내용을 만든다(`shared/chat_share.py` 에 등록, router 가 import 하면 등록된다).

내 줄(주인이 나인 일정)만 담는다: 같은 가족의 남의 줄·다른 가족의 일정·지운 일정은 404. 담는 값은 제목·날짜·시간·장소·종류와
함께하는 사람 이름뿐이고 메모는 담지 않는다. 읽은 값을 그 자리에서 복사한 것이라 나중에 일정을 고쳐도 카드는 그대로다."""

from datetime import date, time
from typing import Any

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.shared import chat_share
from app.shared.errors import not_found

from . import repository as repo
from . import service
from .models import Event
from .timeutil import local_tz


def _hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _date_of(event: Event) -> date | None:
    if event.start_date is not None:
        return event.start_date
    return event.starts_at.astimezone(local_tz()).date() if event.starts_at else None


def event_card(
    db: Session, group_id: str, user_id: str, ref: str, peer_id: str | None
) -> dict[str, Any]:
    event = repo.get(db, group_id, ref, user_id)  # user_id 를 꼭 넘긴다: 안 넘기면 남의 줄도 읽힌다
    if event is None or not service.owns(event, user_id):
        raise not_found("일정")
    event = service.with_sharing(db, user_id, [event])[0]
    names = {u.id: u.name for u in group_repo.members(db, group_id)}
    day = _date_of(event)
    return {
        "title": event.title,
        "date": day.isoformat() if day else None,
        "start_time": _hhmm(event.start_time),
        "end_time": _hhmm(event.end_time),
        "place": event.place or "",
        "kind": event.kind,
        "with_names": [names[i] for i in event.shared_ids if i in names],
    }


chat_share.register_provider(chat_share.EVENT, event_card)
