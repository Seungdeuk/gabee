"""고정 메시지(공지) 업무 규칙. 방 안의 모든 구성원이 고정·해제할 수 있고, 방당 최대 2개(3번째를 고정하면 가장
오래된 고정이 자동 해제된다). 글자가 있는 텍스트 메시지만 고정한다. AI·외부 호출이 없고 메시지 글자를 로그에 남기지 않는다.

권한: resolve_room 으로 방에 들어갈 수 있는지 확인한다(다른 가족·참여하지 않은 1:1 방은 404). 고정은 메시지를
가리키기만 하고 메시지를 바꾸거나 지우지 않는다."""

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import pin_repository as prepo
from . import repository as repo
from .models import ChatPinnedMessage, Message
from .pin_schemas import PinItem, PinResult, PinsOut
from .service import resolve_room

TEXT_LIMIT = 200  # 응답에 싣는 본문 최대 글자 수
WRITE_LIMIT = 30  # 사용자별 분당 고정·해제 수
WINDOW_SECONDS = 60

limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def _check_rate(user_id: str) -> None:
    key = f"chatpin:{user_id}"
    wait = limiter.retry_after(key, WRITE_LIMIT, WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_requests",
            "고정을 너무 자주 바꿨어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    limiter.record(key)


def _item(pin: ChatPinnedMessage, m: Message, author: str, pinner: str) -> PinItem:
    return PinItem(
        message_id=m.id,
        text=m.text[:TEXT_LIMIT],
        text_truncated=len(m.text) > TEXT_LIMIT,
        user_id=m.user_id,
        user_name=author,
        created_at=m.created_at,
        pinned_by=pin.pinned_by,
        pinned_by_name=pinner,
        pinned_at=pin.pinned_at,
    )


def list_pins(db: Session, user: User, group_id: str, room_id: str | None = None) -> PinsOut:
    room = resolve_room(db, user, group_id, room_id)
    rows = prepo.pin_rows(db, room.id, prepo.MAX_PINS)
    return PinsOut(items=[_item(p, m, a, b) for p, m, a, b in rows])


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
        pin_row = prepo.add_pin(db, group_id, room.id, message.id, user.id)
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
    item = _item(pin_row, message, author, pinner)
    db.commit()
    return PinResult(item=item, replaced_message_id=replaced, already_pinned=already)


def unpin(db: Session, user: User, group_id: str, message_id: int, room_id: str | None) -> None:
    _check_rate(user.id)
    room = resolve_room(db, user, group_id, room_id)
    if not prepo.delete_pin(db, room.id, message_id):
        raise not_found("고정된 메시지")
