"""게시판 목록 업무 규칙. 공지로 올린 메시지의 기록을 최신순으로 보고(내려가거나 교체된 지난 공지 포함), 구성원 누구나 글을 지운다.
방 안에서만 보이고(다른 가족·참여하지 않은 1:1 방은 404) AI·외부 호출이 없다. 본문은 로그에 남기지 않는다."""

import base64
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found

from . import board_repository as brepo
from . import pin_repository as prepo
from .board_schemas import BoardItem, BoardOut
from .pin_service import _check_rate
from .service import resolve_room


def encode_cursor(at: datetime, post_id: str) -> str:
    """다음 쪽 기준(올린 시각, id)을 바깥에 내보내는 값으로. 뜻을 알아볼 필요가 없어 base64 로 감싼다."""
    stamp = (
        at.replace(tzinfo=UTC).isoformat() if at.tzinfo is None else at.astimezone(UTC).isoformat()
    )
    return base64.urlsafe_b64encode(f"{stamp}|{post_id}".encode()).decode()


def decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        stamp, post_id = base64.urlsafe_b64decode(value.encode()).decode().split("|", 1)
        at = datetime.fromisoformat(stamp)
    except (ValueError, UnicodeDecodeError):
        raise bad_request("invalid_cursor", "다음 쪽을 불러올 수 없어요") from None
    if not post_id:
        raise bad_request("invalid_cursor", "다음 쪽을 불러올 수 없어요")
    return (at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)), post_id


def list_board(
    db: Session,
    user: User,
    group_id: str,
    room_id: str | None,
    limit: int,
    before: str | None,
) -> BoardOut:
    room = resolve_room(db, user, group_id, room_id)
    cursor = decode_cursor(before) if before else None
    rows = brepo.list_page(db, room.id, limit, cursor)
    page, extra = rows[:limit], rows[limit:]
    items = [
        BoardItem(
            id=p.id,
            message_id=p.message_id,
            text=p.text,
            user_id=m.user_id,
            user_name=author,
            message_created_at=m.created_at,
            posted_by=p.posted_by,
            posted_by_name=poster,
            posted_at=p.posted_at,
            is_current=current,
            message_deleted=m.deleted_at is not None,
        )
        for p, m, author, poster, current in page
    ]
    next_before = encode_cursor(page[-1][0].posted_at, page[-1][0].id) if extra else None
    return BoardOut(items=items, next_before=next_before)


def delete_post(db: Session, user: User, group_id: str, post_id: str, room_id: str | None) -> None:
    """게시판 글을 지운다(구성원 누구나). 지금 공지로 올라 있으면 고정 바에서도 내려간다(나만 숨기기 기록도 함께). 없으면 404."""
    _check_rate(user.id, "chatboard", "게시판")
    room = resolve_room(db, user, group_id, room_id)
    prepo.lock_room(db, room.id)  # 고정 변경과 같은 순서로 처리한다
    # 글은 잠금을 잡은 **뒤에** 읽는다. 잠금 전에 읽으면, 기다리는 사이 다른 요청이 그 글을 지우고 같은 메시지를 새로 올렸을 때
    # 낡은 글 기준으로 새 공지를 고정 바에서 내려 버린다.
    post = brepo.get_post(db, room.id, post_id)
    if post is None:
        raise not_found("게시판 글")
    if brepo.delete_post(db, post) == 0:  # 겹친 삭제가 먼저 지웠다: 고정을 건드리지 않고 끝낸다
        db.rollback()
        raise not_found("게시판 글")
    prepo.delete_pin_in_transaction(db, room.id, post.message_id)
    db.commit()


__all__ = ["ApiError", "delete_post", "list_board"]
