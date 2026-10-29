"""메시지 삭제 업무 규칙: 보낸 사람만, 소프트 삭제(본문·사진을 서버에서도 비운다), 방 접근 규칙은 조회와 같다."""

import logging

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, not_found

from . import photo_service, service
from . import repository as repo
from .schemas import MessageOut

logger = logging.getLogger(__name__)


def delete_message(
    db: Session, user: User, group_id: str, message_id: int, room_id: str | None = None
) -> MessageOut:
    """내가 보낸 메시지를 지운다. 방에 들어갈 수 없거나 이 방의 메시지가 아니면 404, 남이 보낸 메시지(가비의 답 포함)는 403.
    이미 지운 메시지는 그대로 돌려준다(여러 번 눌러도 같은 결과). 사진 메시지는 첨부 행과 원본·썸네일 파일도 지운다."""
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
    files = photo_service.attachment_files(attachment) if attachment else None
    repo.soft_delete(
        db, message, attachment
    )  # DB 를 먼저 저장한다(파일 삭제가 실패해도 사진은 더 보이지 않는다)
    for path in files or ():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("삭제한 사진 파일을 지우지 못했어요")  # 경로·내용은 남기지 않는다
    return service.message_out(message, name)
