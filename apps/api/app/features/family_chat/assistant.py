"""가족 채팅방에서 @가비 로 부른 질문의 답을 '가비' 이름으로 가족 전체방에 저장한다.

- 가비는 사람이 아니라서 사용자 테이블에 계정을 하나 둔다(`ASSISTANT_USER_ID`). 메시지의 보낸 사람 칸을 비울 수 있게 바꾸지 않으므로
  마이그레이션이 없고, 보낸 사람 이름을 조인해 읽는 기존 조회가 그대로 동작한다.
- 이 계정은 로그인할 수 없다: 로그인 아이디·이메일·비밀번호가 없고 토큰은 서버가 만든 임의 값이며 아무에게도 주지 않는다.
- 가족 구성원(group_members)에 넣지 않는다. 구성원 목록·할 일 담당자·읽음 계산에 나오지 않는다.
- 저장은 서버가 AI 답을 만든 직후에만 한다. 앱이 "이 글을 가비 이름으로 올려 줘"라고 요청하는 입구는 두지 않는다(아무 글이나 가비 이름으로 올리는 것을 막는다).
- 기본은 가족 전체방에 저장한다. 1:1 방에서 부른 답은 그 1:1 방(두 사람에게만 보임)에 저장한다(`room_id`)."""

import re
import secrets
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import room_assistant
from app.shared.privacy import restore_value

from . import ai_service
from . import repository as repo
from .models import ASSISTANT_NAME, ASSISTANT_USER_ID, Message
from .schemas import MessageOut
from .service import message_out, open_direct_room, post

MAX_TEXT = 2000  # 사람이 보내는 메시지의 길이 제한과 같다


def get_or_create_assistant(db: Session) -> User:
    """가비 계정. 없으면 만든다(동시에 만들다 겹치면 먼저 만들어진 것을 쓴다)."""
    user = db.get(User, ASSISTANT_USER_ID)
    if user is not None:
        return user
    try:
        user = User(
            id=ASSISTANT_USER_ID,
            name=ASSISTANT_NAME,
            role="other",
            token=secrets.token_urlsafe(32),
        )
        db.add(user)
        db.commit()
        return user
    except IntegrityError:
        db.rollback()
        return db.get(User, ASSISTANT_USER_ID)


_CITATION = re.compile(r"\s*\[\d+\]")
_HEADING = re.compile(r"^[ 	]{0,3}#{1,6}[ 	]*", re.MULTILINE)
_BULLET = re.compile(r"^[ 	]*[-*][ 	]+", re.MULTILINE)
_LIST_DATE = re.compile(r"^• (\d{4})-(\d{2})-(\d{2})[:：]?[ 	]*", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")


def _short_date(match: re.Match) -> str:
    year, month, day = match.groups()
    # 올해 날짜는 연도를 빼서 줄을 짧게 한다(말풍선이 좁아 날짜가 길면 줄이 어색하게 꺾인다)
    return f"• {month}/{day} " if int(year) == date.today().year else f"• {year}-{month}-{day} "


def plain(text: str) -> str:
    """방 메시지는 일반 글이라 개인 대화 화면이 그리는 마크다운 표시('## 제목', '**굵게**')를 글자 그대로 보이지 않게 뺀다.
    읽기 쉽게 목록 줄의 '- '·'* ' 는 '• ' 로, 목록 줄 맨 앞의 올해 날짜(2026-11-04)는 '11/04' 로 줄이고, 빈 줄은 한 줄까지만 둔다.
    번호 목록과 문장 속 날짜는 그대로 둔다."""
    text = _HEADING.sub("", text).replace("**", "")
    text = _BULLET.sub("• ", text)
    text = _LIST_DATE.sub(_short_date, text)
    return _BLANK_LINES.sub("\n\n", text)


def clip(text: str) -> str:
    """방에 올릴 글로 다듬는다: 출처 번호([1])는 개인 대화의 출처 칩과 이어지는 표시라 방 메시지에서는 뺀다. 마크다운 표시도 뺀다. 길면 줄인다."""
    text = plain(_CITATION.sub("", text)).strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def direct_room(db: Session, user: User, group_id: str, room_id: str | None) -> str | None:
    """@가비 를 부른 방. 1:1 방이면 그 방 id, 가족 전체방이거나 room_id 가 없으면 None.
    1:1 방은 참가자 본인만(아니면 404), 상대가 방이나 가족을 나갔으면 403 peer_left — AI 대화 도우미와 같은 규칙이다."""
    return ai_service.room_scope(db, user, group_id, room_id)


class RoomContext:
    """@가비 에 맥락으로 붙일 방의 최근 대화(개인정보를 가린 것). 쓴 뒤 close() 로 이름 대응표를 지운다."""

    def __init__(self, ctx: ai_service._Context) -> None:
        self._ctx = ctx

    @property
    def transcript(self) -> str:
        return self._ctx.transcript

    def restore(self, text: str) -> str:
        """모델이 쓴 이름 토큰을 원래 이름으로 되돌린다(정책의 복원 종류만)."""
        return restore_value(self._ctx.prep, text, generalize_unknown=True, scrub=True).value

    def close(self) -> None:
        self._ctx.close()


def room_context(
    db: Session, group_id: str, direct: str | None, user_id: str | None = None
) -> RoomContext | None:
    """@가비 에 맥락으로 붙일 방의 최근 대화. 붙일 메시지가 없으면 None."""
    ctx = ai_service.room_context(db, group_id, direct, user_id)
    return RoomContext(ctx) if ctx else None


def post_as_assistant(
    db: Session, group_id: str, text: str, room_id: str | None = None
) -> MessageOut:
    """가비 이름으로 메시지를 올린다(room_id 가 없으면 가족 전체방, 있으면 그 1:1 방). group_id 는 호출한 쪽이 실제 구성원인지 확인한 값이어야 한다."""
    assistant = get_or_create_assistant(db)
    # room_id 는 direct_room 이 확인한 1:1 방 id 여야 한다(없으면 가족 전체방)
    target = room_id or repo.get_family_room(db, group_id).id
    message = repo.add(
        db, Message(group_id=group_id, room_id=target, user_id=assistant.id, text=clip(text))
    )
    return message_out(message, assistant.name)


def share_as_user(
    db: Session, user: User, group_id: str, text: str, peer_id: str | None = None
) -> MessageOut:
    """사용자가 AI 채팅에서 확인한 글을 그 사람 이름으로 보낸다(peer_id 가 없으면 가족 전체방, 있으면 그 사람과의 1:1 방).
    구성원 확인·저장·푸시는 일반 메시지와 같은 길을 탄다."""
    room_id = open_direct_room(db, user, group_id, peer_id).id if peer_id else None
    return post(db, user, group_id, text, room_id)


room_assistant.register_poster(lambda db, group_id, text: post_as_assistant(db, group_id, text).id)
