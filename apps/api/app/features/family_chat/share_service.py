"""공유 카드 보내기 업무 규칙. 방 규칙은 일반 메시지와 같다(방에 들어갈 수 없으면 404, 상대가 나간 1:1 방이면 409).
카드 내용은 데이터 주인 기능이 서버에서 만든다(`shared/chat_share.py`). 메시지 글자는 개인정보 없는 고정 문구다."""

import json

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_share
from app.shared.errors import ApiError, bad_request

from . import chat_push, service
from . import repository as repo
from .models import DIRECT, Message
from .schemas import MessageOut, ShareCreate

SHARE_LIMIT = 10  # 한 사람이 1분에 보낼 수 있는 카드 수
SHARE_WINDOW_SECONDS = 60


def _check_rate(user_id: str) -> None:
    key = f"chatshare:{user_id}"
    wait = chat_share.limiter.retry_after(key, SHARE_LIMIT, SHARE_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_shares",
            "카드를 너무 자주 보냈어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    chat_share.limiter.record(key)


def send(db: Session, user: User, group_id: str, body: ShareCreate) -> MessageOut:
    room = service.resolve_room(db, user, group_id, body.room_id)
    service.ensure_can_send(room)
    _check_rate(user.id)
    peer_id = None
    if room.kind == DIRECT:  # 1:1 방이면 그 상대와 관련된 내용만 담는다
        peer_id = next((i for i in repo.room_member_ids(db, room) if i != user.id), None)
    payload = chat_share.build(db, body.kind, group_id, user.id, body.ref, peer_id)
    if len(json.dumps(payload, ensure_ascii=False)) > chat_share.MAX_PAYLOAD_BYTES:
        raise bad_request("share_too_large", "공유할 내용이 너무 길어요")
    message = repo.add(
        db,
        Message(
            group_id=group_id,
            room_id=room.id,
            user_id=user.id,
            text=chat_share.SUMMARY_TEXT[body.kind],
        ),
    )
    repo.add_share(db, message, body.kind, payload)
    repo.advance_read(db, room.id, user.id, message.id)  # 내가 보낸 카드는 읽은 것으로
    chat_push.notify_new_message(db, room, message)  # 고정 문구 푸시(카드 내용은 싣지 않는다)
    return service.message_view(db, room, (message, user.name), user.id)
