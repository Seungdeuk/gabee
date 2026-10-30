"""채팅방 사진·파일·동영상 모음. 읽기 전용이며 AI·외부 서비스를 부르지 않고 사용자 데이터를 로그에 남기지 않는다.

권한: resolve_room 으로 방에 들어갈 수 있는지 확인(아니면 404)하고, 조회도 그 방의 메시지 조건(SQL)으로만 한다.
"""

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError
from app.shared.rate_limit import FailureLimiter

from . import media_repository as media_repo
from . import service
from .media_schemas import MediaCounts, MediaItem, MediaPage
from .models import MessageAttachment

LIMIT_PER_MINUTE = 60
WINDOW_SECONDS = 60
limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def attachment_kind(a: MessageAttachment) -> str:
    """첨부의 종류를 정하는 유일한 곳. MessageAttachment.kind(image | file)를 읽는다(동영상은 아직 없다).
    목록·개수의 종류 필터도 같은 칼럼으로 SQL 조건에 넣는다(list_media, counts)."""
    return "file" if a.kind == "file" else "image"


def _check_rate(user_id: str) -> None:
    key = f"chatmedia:{user_id}"
    wait = limiter.retry_after(key, LIMIT_PER_MINUTE, WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_requests",
            "너무 자주 불러왔어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    limiter.record(key)


def _item(a: MessageAttachment, message_id: int, user_id: str, user_name: str, created_at):
    if attachment_kind(a) == "file":
        return MediaItem(
            attachment_id=a.id,
            message_id=message_id,
            kind="file",
            user_id=user_id,
            user_name=user_name,
            created_at=created_at,
            url=f"/family-chat/files/{a.id}",
            thumb_url=None,
            width=None,
            height=None,
            size_bytes=a.size_bytes,
        )
    return MediaItem(
        attachment_id=a.id,
        message_id=message_id,
        kind=attachment_kind(a),
        user_id=user_id,
        user_name=user_name,
        created_at=created_at,
        url=f"/family-chat/photos/{a.id}",
        thumb_url=f"/family-chat/photos/{a.id}?size=thumb",
        width=a.width,
        height=a.height,
        size_bytes=a.size_bytes,
    )


def list_media(
    db: Session,
    user: User,
    group_id: str,
    room_id: str | None,
    kind: str,
    limit: int,
    before_id: int | None,
) -> MediaPage:
    room = service.resolve_room(db, user, group_id, room_id)
    _check_rate(user.id)
    by_kind = media_repo.count_attachments(db, room)
    counts = MediaCounts(image=by_kind.get("image", 0), file=by_kind.get("file", 0), video=0)
    if kind not in ("all", "image", "file"):  # 동영상은 아직 없다
        return MediaPage(items=[], next_before_id=None, counts=counts)
    rows = media_repo.list_page(db, room, limit, before_id, None if kind == "all" else kind)
    page = rows[:limit]
    items = [_item(a, m.id, m.user_id, name, m.created_at) for a, m, name in page]
    next_id = page[-1][1].id if len(rows) > limit else None
    return MediaPage(items=items, next_before_id=next_id, counts=counts)
