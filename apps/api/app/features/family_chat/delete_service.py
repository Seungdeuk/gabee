"""메시지 삭제 업무 규칙: 보낸 사람만, 소프트 삭제(본문·사진을 서버에서도 비운다), 방 접근 규칙은 조회와 같다."""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_library
from app.shared.errors import ApiError, not_found

from . import file_service, service
from . import repository as repo
from .schemas import DeletedOut, MessageOut

logger = logging.getLogger(__name__)


def delete_message(
    db: Session, user: User, group_id: str, message_id: int, room_id: str | None = None
) -> MessageOut:
    """내가 보낸 메시지를 지운다. 방에 들어갈 수 없거나 이 방의 메시지가 아니면 404, 남이 보낸 메시지(가비의 답 포함)는 403.
    이미 지운 메시지는 그대로 돌려준다(여러 번 눌러도 같은 결과). 사진·문서 메시지는 첨부 행과 디스크 파일도 지운다."""
    room = service.resolve_room(db, user, group_id, room_id)
    found = repo.get_in_room(db, room, message_id)
    if found is None:
        raise not_found("메시지")
    message, name = found
    if message.user_id != user.id:
        raise ApiError(403, "forbidden", "내가 보낸 메시지만 지울 수 있어요")
    if message.deleted_at is not None:
        return service.message_out(message, name)
    attachment = repo.attachments_for(db, [message.id]).get(message.id)
    files = file_service.attachment_paths(attachment) if attachment else ()
    # 파일을 먼저 지운다. 지우다 실패하면 DB 는 그대로라 다시 눌러 지울 수 있고, 파일만 남는 일이 없다
    # (반대로 DB 가 먼저면 첨부 행이 사라져 남은 파일의 경로를 다시 찾을 수 없다). 파일이 이미 없어도 괜찮다.
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("삭제할 첨부 파일을 지우지 못했어요")  # 경로·내용은 남기지 않는다
            raise ApiError(
                500, "delete_failed", "메시지를 지우지 못했어요. 다시 시도해 주세요"
            ) from None
    repo.soft_delete(db, message, attachment)
    if (
        attachment is not None
    ):  # 이 첨부에서 만든 문서함 기록이 있으면 함께 지운다(없으면 아무 일도 없다)
        chat_library.attachment_removed(db, group_id, attachment.id)
    return service.message_out(message, name)


def deleted_since(
    db: Session, user: User, group_id: str, since: datetime, room_id: str | None = None
) -> DeletedOut:
    """since 이후에 지워진 이 방의 메시지 id. 앱은 새 메시지만 조회하므로, 이미 받아 둔 메시지가 지워졌는지는
    이 조회로 안다. server_time 은 서버 시계라 다음 조회의 since 로 쓰면 기기 시계가 어긋나도 놓치지 않는다."""
    room = service.resolve_room(db, user, group_id, room_id)
    now = datetime.now(UTC)
    return DeletedOut(message_ids=repo.deleted_since(db, room, since), server_time=now)
