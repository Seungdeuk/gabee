"""같이해요 부탁: 보내기·목록·답하기·취소.
보낸 사람은 events_requests.user_id, 받는 사람은 events_request_recipients 줄들이다.
수락하면 수락한 사람 본인의 일정만 만들고(보낸 사람에게는 만들지 않는다), 답은 현황으로만 보인다."""

import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.shared.errors import ApiError, bad_request, not_found
from app.shared.notifications import notify

from . import repository as repo
from .constants import (
    KIND_TODO,
    RECIPIENT_ACCEPTED,
    RECIPIENT_DECLINED,
    RECIPIENT_WAITING,
)
from .models import Event, EventRequest, EventRequestRecipient
from .schemas import RequestAnswer, RequestCreate, RequestRecipients
from .timeutil import local_tz

_STATUS = {
    RECIPIENT_WAITING: "waiting",
    RECIPIENT_ACCEPTED: "accepted",
    RECIPIENT_DECLINED: "declined",
}
_ALL_DAY = (time(0, 0), time(23, 59))  # 종일은 00:00~23:59 (events 와 같은 규칙)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _notify_received(db: Session, req: EventRequest, to_ids: list[str]) -> None:
    """받는 사람에게 "같이해요가 도착했어요". 문구는 고정이라 제목·날짜·장소·메모를 담지 않는다."""
    notify(
        db,
        group_id=req.group_id,
        kind="schedule",
        event="request_received",
        recipients=to_ids,
        title="같이해요가 도착했어요",
        target_type="schedule_request",
        target_id=req.id,
        actor_user_id=req.user_id,
    )


def _out(
    req: EventRequest,
    recipients: list[EventRequestRecipient],
    my_events: list[Event],
    viewer_id: str,
) -> dict:
    """받는 사람은 누가 또 받았는지 모른다: 보낸 사람에게는 전원, 받는 사람에게는 내 줄과 수락한 사람만 보여 준다."""
    sender = req.user_id == viewer_id
    return {
        "id": req.id,
        "from_id": req.user_id,
        "title": req.title,
        "start_date": req.start_date,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "place": req.place,
        "memo": req.memo,
        "created_at": req.created_at,
        "canceled": req.canceled_at is not None,
        "recipients": [
            {"user_id": r.user_id, "status": _STATUS.get(r.status, "waiting")}
            for r in recipients
            if r.request_id == req.id
            and (sender or r.user_id == viewer_id or r.status == RECIPIENT_ACCEPTED)
        ],
        "my_event_id": next((e.id for e in my_events if e.request_id == req.id), None),
        "edited_at": req.edited_at,
    }


def _outs(db: Session, reqs: list[EventRequest], user_id: str) -> list[dict]:
    if not reqs:
        return []
    ids = [r.id for r in reqs]
    recipients = repo.recipients_of(db, ids)
    mine = repo.live_events_of_requests(db, ids, user_id)
    return [_out(r, recipients, mine, user_id) for r in reqs]


def create(db: Session, group_id: str, user_id: str, body: RequestCreate) -> dict:
    to_ids = list(dict.fromkeys(body.to_ids))
    if user_id in to_ids:
        raise bad_request("invalid_recipients", "나에게는 보낼 수 없어요")
    if set(to_ids) - repo.member_ids(db, group_id, to_ids):
        raise bad_request("invalid_recipients", "같은 가족 구성원이 아닌 사람이 있어요")
    if body.end_time is not None and body.start_time is None:
        raise bad_request("invalid_time", "시작하는 시간이 없으면 끝나는 시간을 정할 수 없어요")
    if body.start_time and body.end_time and body.end_time <= body.start_time:
        raise bad_request("invalid_time", "끝나는 시간은 시작하는 시간보다 늦어야 해요")
    now = datetime.now(UTC)
    req = EventRequest(
        id=_new_id(),
        group_id=group_id,
        user_id=user_id,
        title=body.title,
        place=body.place.strip(),
        memo=body.memo,
        start_date=body.start_date,
        start_time=body.start_time,
        end_time=body.end_time,
        created_at=now,
    )
    # 받는 사람 순서는 보낸 순서다(created_at 이 같으면 id 가 무작위라 1μs 씩 늘린다)
    rows = [
        EventRequestRecipient(
            id=_new_id(),
            group_id=group_id,
            user_id=t,
            request_id=req.id,
            created_at=now + timedelta(microseconds=i),
        )
        for i, t in enumerate(to_ids)
    ]
    db.add(req)
    db.flush()  # 부탁 줄이 먼저 들어가야 받는 사람 줄이 가리킬 수 있다
    db.add_all(rows)
    _notify_received(db, req, to_ids)
    db.commit()
    return _out(req, rows, [], user_id)


def list_mine(db: Session, group_id: str, user_id: str) -> list[dict]:
    return _outs(db, repo.requests_for(db, group_id, user_id), user_id)


def answer(db: Session, group_id: str, user_id: str, request_id: str, body: RequestAnswer) -> dict:
    """받는 사람 본인이 수락·어렵겠어요로 답한다. 이미 답했다면 날짜가 지나기 전까지만 바꿀 수 있다.
    수락하면 내 일정을 만들고, 답을 바꾸면 이전에 만든 내 일정은 지운다(소프트 삭제)."""
    req = repo.get_request(db, group_id, request_id)
    recip = repo.my_recipient(db, request_id, user_id) if req is not None else None
    if req is None or recip is None:
        raise not_found("부탁")
    if req.canceled_at is not None:
        raise bad_request("request_canceled", "취소된 부탁이에요")
    accepted = body.answer == "accepted"
    if accepted and body.kind is None:
        raise bad_request("kind_required", "수락하려면 약속인지 할 일인지 골라야 해요")
    if recip.status != RECIPIENT_WAITING and req.start_date < datetime.now(local_tz()).date():
        raise bad_request("answer_locked", "날짜가 지나서 답을 바꿀 수 없어요")

    previous = repo.live_events_of_recipient(db, recip.id)
    keep = accepted and any(e.kind == body.kind for e in previous)  # 같은 종류로 다시 수락
    now = datetime.now(UTC)
    for event in previous:
        if not (keep and event.kind == body.kind):
            event.deleted_at = now
    new_status = RECIPIENT_ACCEPTED if accepted else RECIPIENT_DECLINED
    changed = recip.status != new_status  # 같은 답을 다시 보내면 알리지 않는다
    recip.status = new_status
    recip.answered_at = now
    if accepted and not keep:
        db.add(_event_from(req, recip, user_id, body.kind))
    if changed:
        notify(
            db,
            group_id=group_id,
            kind="schedule",
            event="request_answered",
            recipients=[req.user_id],
            title="같이해요에 답이 왔어요",  # 수락·거절 여부와 누가 답했는지는 담지 않는다
            target_type="schedule_request",
            target_id=req.id,
            actor_user_id=user_id,
        )
    db.commit()
    return _outs(db, [req], user_id)[0]


FROM_TOGETHER_NOTE = "함께하기에서 등록된 일정입니다."


def _accepted_memo(memo: str) -> str:
    """수락해서 생기는 일정의 메모: 부탁의 메모를 그대로 두고 줄바꿈 한 번 뒤에 안내 한 줄을 붙인다(부탁 메모가 없으면 이 한 줄만)."""
    return f"{memo}\n{FROM_TOGETHER_NOTE}" if memo else FROM_TOGETHER_NOTE


def _event_from(req: EventRequest, recip: EventRequestRecipient, user_id: str, kind: int) -> Event:
    """부탁 그대로 받는 사람의 일정 한 줄을 만든다. 종일 부탁을 할 일로 받으면 시간은 비운다."""
    start, end = req.start_time, req.end_time
    if kind == KIND_TODO and (start, end) == _ALL_DAY:
        start = end = None
    starts_at = datetime.combine(req.start_date, start or time(0, 0), tzinfo=local_tz())
    return Event(
        id=_new_id(),
        group_id=req.group_id,
        user_id=user_id,
        created_by=user_id,
        title=req.title,
        starts_at=starts_at.astimezone(UTC),
        note=_accepted_memo(req.memo),
        memo=_accepted_memo(req.memo),
        status="confirmed",
        source="request",
        kind=kind,
        place=req.place,
        start_date=req.start_date,
        start_time=start,
        end_time=end,
        request_id=req.id,
        recip_id=recip.id,
    )


def cancel(db: Session, group_id: str, user_id: str, request_id: str) -> dict:
    """보낸 사람만 취소한다. 수락한 사람이 있어도 취소되고, 그 사람들이 수락해서 만든 일정은 같이 지운다(소프트 삭제).
    이미 취소했으면 그대로다."""
    req = _owned_request(db, group_id, user_id, request_id)
    if req.canceled_at is None:
        now = datetime.now(UTC)
        req.canceled_at = now
        for event in repo.live_events_of_request(db, req.id):
            event.deleted_at = now
        db.commit()
    return _outs(db, [req], user_id)[0]


def _owned_request(db: Session, group_id: str, user_id: str, request_id: str) -> EventRequest:
    """내가 보낸 부탁. 없거나 나와 상관없는 부탁은 404, 받는 사람이 고치려 하면 403."""
    req = repo.get_request(db, group_id, request_id)
    if req is None or (
        req.user_id != user_id and repo.my_recipient(db, request_id, user_id) is None
    ):
        raise not_found("부탁")
    if req.user_id != user_id:
        raise ApiError(403, "not_owner", "내가 보낸 부탁만 바꿀 수 있어요")
    return req


def change_memo(db: Session, group_id: str, user_id: str, request_id: str, memo: str) -> dict:
    """보낸 사람이 부탁의 메모만 고친다(수락 여부와 상관없이). 이미 수락한 사람의 일정은 독립이라 바뀌지 않고, 고친 뒤에 수락하면
    고친 메모가 새 일정의 메모에 들어간다. 제목·날짜·시간·장소는 못 바꾼다."""
    req = _owned_request(db, group_id, user_id, request_id)
    if req.canceled_at is not None:
        raise bad_request("request_canceled", "취소된 부탁이에요")
    req.memo = memo
    req.edited_at = datetime.now(UTC)
    db.commit()
    return _outs(db, [req], user_id)[0]


def change_recipients(
    db: Session, group_id: str, user_id: str, request_id: str, body: RequestRecipients
) -> dict:
    """받는 사람을 body.to_ids 로 다시 정한다(보낸 사람만, 답을 했든 안 했든). 빠진 사람의 답 줄은 지우고, 그 사람이
    수락해서 만든 일정은 같이 지운다(소프트 삭제, 줄을 지우기 전에 일정의 연결을 끊는다). 새로 든 사람에게는 새 부탁으로 간다.
    내용(제목·날짜 등)은 못 바꾼다."""
    req = _owned_request(db, group_id, user_id, request_id)
    if req.canceled_at is not None:
        raise bad_request("request_canceled", "취소된 부탁이에요")
    to_ids = list(dict.fromkeys(body.to_ids))
    if user_id in to_ids:
        raise bad_request("invalid_recipients", "나에게는 보낼 수 없어요")
    if set(to_ids) - repo.member_ids(db, group_id, to_ids):
        raise bad_request("invalid_recipients", "같은 가족 구성원이 아닌 사람이 있어요")

    now = datetime.now(UTC)
    rows = repo.recipients_of(db, [req.id])
    kept = {r.user_id for r in rows if r.user_id in to_ids}
    removed = [r for r in rows if r.user_id not in to_ids]
    added = [t for t in to_ids if t not in kept]
    if not removed and not added:
        return _outs(db, [req], user_id)[0]
    for row in removed:
        for event in repo.events_of_recipient(db, row.id):
            event.recip_id = None
            if event.deleted_at is None:
                event.deleted_at = now
    db.flush()  # 일정의 연결을 먼저 끊어야 답 줄을 지울 수 있다
    for row in removed:
        db.delete(row)
    db.add_all(
        [
            EventRequestRecipient(
                id=_new_id(),
                group_id=group_id,
                user_id=t,
                request_id=req.id,
                created_at=now + timedelta(microseconds=i),
            )
            for i, t in enumerate(added)
        ]
    )
    req.edited_at = now
    _notify_received(db, req, added)
    db.commit()
    return _outs(db, [req], user_id)[0]
