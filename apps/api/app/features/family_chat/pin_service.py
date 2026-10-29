"""게시판(고정 메시지, 공지) 업무 규칙. 방 안의 모든 구성원이 올리고 내릴 수 있고, 방당 최대 2개(3번째를 올리면 가장
오래된 것이 자동으로 내려간다). 글자가 있는 텍스트 메시지만 올린다. 올릴 때 보이는 범위의 본문을 사본으로 저장해
원본 메시지를 보낸 사람이 지워도 게시판에는 남는다(내리면 사본도 사라진다). 사용자마다 "나만 숨기기"를 따로 할 수 있다.
AI·외부 호출이 없고 메시지 글자를 로그에 남기지 않는다.

권한: resolve_room 으로 방에 들어갈 수 있는지 확인한다(다른 가족·참여하지 않은 1:1 방은 404). 게시판은 원본 메시지를
바꾸거나 지우지 않는다."""

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import board_repository as brepo
from . import pin_repository as prepo
from . import repository as repo
from .models import ChatPinnedMessage, Message
from .pin_schemas import PinItem, PinResult, PinsOut
from .service import resolve_room

TEXT_LIMIT = 200  # 응답에 싣는 본문 최대 글자 수
WRITE_LIMIT = 30  # 사용자별 분당 고정·해제 수
WINDOW_SECONDS = 60

limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def _check_rate(user_id: str, kind: str = "chatpin", what: str = "고정") -> None:
    key = f"{kind}:{user_id}"
    wait = limiter.retry_after(key, WRITE_LIMIT, WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_requests",
            f"{what}을 너무 자주 바꿨어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    limiter.record(key)


def _item(
    pin: ChatPinnedMessage, m: Message, author: str, pinner: str, hidden: bool = False
) -> PinItem:
    # 올릴 때의 본문 사본을 쓴다. 사본이 없는 옛 행은 원본 본문(지워졌으면 빈 글자)으로 대신한다
    text = pin.text if pin.text is not None else m.text
    return PinItem(
        message_id=m.id,
        text=text[:TEXT_LIMIT],
        text_truncated=len(text) > TEXT_LIMIT,
        user_id=m.user_id,
        user_name=author,
        created_at=m.created_at,
        pinned_by=pin.pinned_by,
        pinned_by_name=pinner,
        pinned_at=pin.pinned_at,
        message_deleted=m.deleted_at is not None,
        hidden=hidden,
    )


def list_pins(db: Session, user: User, group_id: str, room_id: str | None = None) -> PinsOut:
    room = resolve_room(db, user, group_id, room_id)
    rows = prepo.pin_rows(db, room.id, prepo.MAX_PINS, user.id)
    return PinsOut(items=[_item(p, m, a, b, h) for p, m, a, b, h in rows])


def pin(db: Session, user: User, group_id: str, message_id: int, room_id: str | None) -> PinResult:
    _check_rate(user.id)
    room = resolve_room(db, user, group_id, room_id)
    found = repo.get_in_room(db, room, message_id)
    if found is None:
        raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
    message, author = found
    if not message.text.strip() or repo.attachments_for(db, [message.id]):
        raise bad_request("not_pinnable", "글자가 있는 메시지만 고정할 수 있어요")

    prepo.lock_room(db, room.id)  # 같은 방의 고정 변경은 한 번에 하나씩(아래 개수 정리까지)
    replaced: int | None = None
    pin_row = prepo.get_pin(db, room.id, message.id)
    pinner = prepo.user_name(db, pin_row.pinned_by) if pin_row else user.name
    already = pin_row is not None
    if not already:
        # 사본은 게시판에 보이는 범위만 저장한다(+1 은 잘렸는지 알아보려는 한 글자). 지운 긴 메시지의 나머지는 남기지 않는다
        snapshot = message.text[: TEXT_LIMIT + 1]
        pin_row = prepo.add_pin(db, group_id, room.id, message.id, user.id, snapshot)
        if pin_row is None:  # 겹친 요청이 먼저 고정했다(유니크 충돌)
            already = True
            pin_row = prepo.get_pin(db, room.id, message.id)
            pinner = prepo.user_name(db, pin_row.pinned_by) if pin_row else user.name
        else:
            others = [p for p in prepo.pins_in_room(db, room.id) if p.message_id != message.id]
            extra = others[prepo.MAX_PINS - 1 :]  # 새 고정을 포함해 최근 MAX_PINS 개만 남긴다
            if extra:
                prepo.remove_pins(db, room.id, [p.message_id for p in extra])
                replaced = extra[-1].message_id  # 가장 오래된 고정
    if pin_row is None:  # 겹친 고정이 곧바로 해제된 드문 경우
        raise ApiError(409, "pin_changed", "고정 상태가 바뀌었어요. 다시 시도해 주세요")
    # 응답은 commit 전에, 잠금 안에서 만든다(commit 뒤 다시 조회하면 그 사이 다른 구성원의 해제·교체와 겹칠 수 있다)
    if not already or not brepo.has_post(db, room.id, message.id):
        # 게시판 목록(지난 공지 포함)용 기록: 올릴 때의 전체 본문을 남긴다. 이미 올라 있던 공지는 기록이 없을 때만(옛 공지) 만든다
        brepo.upsert_post(db, group_id, room.id, message.id, user.id, message.text)
    item = _item(pin_row, message, author, pinner, prepo.is_hidden(db, pin_row.id, user.id))
    db.commit()
    return PinResult(item=item, replaced_message_id=replaced, already_pinned=already)


def unpin(db: Session, user: User, group_id: str, message_id: int, room_id: str | None) -> None:
    _check_rate(user.id)
    room = resolve_room(db, user, group_id, room_id)
    if not prepo.delete_pin(db, room.id, message_id):
        raise not_found("고정된 메시지")


def hide(
    db: Session, user: User, group_id: str, message_id: int, room_id: str | None, hidden: bool
) -> PinItem:
    """이 공지를 나만 숨기거나(hidden=True) 다시 보이게 한다. 다른 구성원에게는 영향이 없다. 올라가 있지 않은 공지는 404."""
    _check_rate(user.id, "chatpinhide", "숨기기")  # 고정·해제와 한도를 따로 센다
    room = resolve_room(db, user, group_id, room_id)
    pin_row = prepo.get_pin(db, room.id, message_id)
    if pin_row is None:
        raise not_found("고정된 메시지")
    prepo.set_hidden(db, pin_row.id, user.id, hidden)
    rows = prepo.pin_rows(db, room.id, 1, user.id, message_id)
    if not rows:  # 겹친 요청이 그 사이에 내렸다
        raise not_found("고정된 메시지")
    p, m, author, pinner, is_hidden = rows[0]
    return _item(p, m, author, pinner, is_hidden)
