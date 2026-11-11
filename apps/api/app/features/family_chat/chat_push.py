"""소통 푸시: 새 글·사진·파일이 올라오면 받을 사람에게 고정 문구 푸시만 보낸다(알림함에는 남기지 않는다).

푸시에는 글 내용·보낸 사람·방 이름·파일 이름을 싣지 않는다. 실제 메시지는 앱을 연 뒤 인증 API 로 읽는다.
같은 방의 푸시는 방 id 를 합치기 키로 붙여 잠금 화면에 한 건으로 교체한다(안드로이드 `tag`, iOS `collapseId`).
푸시가 실패해도 메시지 전송은 영향받지 않는다."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.push import push_only

from . import repository as repo
from .models import ChatRoom, Message

logger = logging.getLogger(__name__)

TITLE = "새 메시지가 도착했어요"
KIND = "chat"  # 푸시 설정의 분류(사용자가 "소통" 푸시를 끌 수 있다)
BURST_SECONDS = (
    10  # 10초 칸마다 같은 사람이 같은 방에 보낸 첫 글에서만 푸시한다(칸이 바뀌면 다시 푸시)
)
BATCH_WINDOW = timedelta(minutes=10)  # 같은 묶음 번호는 이 안에 올린 사진끼리만 한 묶음으로 본다


def window_start(at: datetime) -> datetime:
    """at 가 속한 BURST_SECONDS 칸의 시작 시각(UTC). 슬라이딩 창이면 대화가 이어지는 동안 첫 글 뒤로는 푸시가 영영 막히므로 고정 칸으로 센다."""
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    epoch = int(at.timestamp())
    return datetime.fromtimestamp(epoch - epoch % BURST_SECONDS, UTC)


def recipients(db: Session, room: ChatRoom, sender_id: str) -> list[str]:
    """푸시를 받을 사람: 방 참여자(가족 전체방은 가족 구성원 전원, 1:1 은 두 사람)에서 보낸 사람과 방 알림을 끈 사람을 뺀다."""
    muted = repo.muted_user_ids(db, room.id)
    return [u for u in repo.room_member_ids(db, room) if u != sender_id and u not in muted]


def notify_new_message(
    db: Session, room: ChatRoom, message: Message, batch_id: str | None = None
) -> None:
    """방금 저장한 메시지를 받을 사람에게 푸시한다. 호출 쪽은 메시지를 이미 저장(커밋)한 상태여야 한다.
    같은 묶음 번호(batch_id)의 사진은 첫 사진에서만, 같은 사람이 연달아 보낸 글은 BURST_SECONDS 안에는 첫 글에서만 보낸다."""
    if not settings.push_enabled:
        return
    try:
        if batch_id and repo.earlier_batch_photo_exists(
            db, room, message, batch_id, datetime.now(UTC) - BATCH_WINDOW
        ):
            return
        if BURST_SECONDS > 0 and repo.sent_since(
            db, room, message, window_start(message.created_at)
        ):
            return
        to = recipients(db, room, message.user_id)
        if not to:
            return
        data = {
            "kind": KIND,
            "room_id": room.id,
        }  # 보낸 사람 id 등 다른 값은 외부 푸시 서버로 보내지 않는다
        push_only(
            db, user_ids=to, kind=KIND, title=TITLE, body=None, data=data, collapse_key=room.id
        )
        db.commit()  # 커밋 뒤에 발송된다(쌓아 둔 푸시는 이 커밋에서 나간다)
    except Exception as exc:  # noqa: BLE001  푸시 실패가 전송을 깨면 안 된다(종류만 기록)
        db.rollback()
        logger.warning("chat push failed error=%s", type(exc).__name__)
