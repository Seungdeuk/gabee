"""메시지-일정·할 일 연결 업무 규칙. 채팅에서 AI 후보를 확인해 일정/할 일로 등록할 때 원본 메시지와의 연결을 저장해
'등록됨' 표시와 원본 메시지로 이동에 쓴다. 같은 (방, 메시지, 종류, 대상)은 한 번만 저장한다(멱등).
삭제는 연결을 만든 사람만 한다. AI·외부 호출이 없고 제목·메시지 글자를 로그에 남기지 않는다.

권한: resolve_room 으로 방에 들어갈 수 있는지 확인한다(다른 가족·참여하지 않은 1:1 방은 404).
일정(schedule)은 다른 기능이라 import 하지 않는다 — kind=event 의 target_id 는 존재를 검증하지 않고 복사본만 저장한다."""

import unicodedata
from datetime import time

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import link_repository as lrepo
from . import repository as repo
from . import todo_repository as todo_repo
from .link_schemas import LinkCreate, LinkOut, LinksOut
from .models import ChatMessageLink, Message
from .service import ensure_can_send, resolve_room

TEXT_LIMIT = 100  # 응답에 싣는 원본 메시지 본문 최대 글자 수
TITLE_LIMIT = 120
WRITE_LIMIT = 30  # 사용자별 분당 연결 생성·삭제 수
WINDOW_SECONDS = 60

limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def _check_rate(user_id: str) -> None:
    key = f"chatlink:{user_id}"
    wait = limiter.retry_after(key, WRITE_LIMIT, WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_requests",
            "연결을 너무 자주 바꿨어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    limiter.record(key)


def _out(link: ChatMessageLink, m: Message, creator: str, author: str) -> LinkOut:
    return LinkOut(
        id=link.id,
        room_id=link.room_id,
        message_id=link.message_id,
        kind=link.kind,
        target_id=link.target_id,
        title=link.title,
        date=link.date,
        time=link.time.strftime("%H:%M") if link.time else None,
        created_by=link.created_by,
        created_by_name=creator,
        created_at=link.created_at,
        message_text=m.text[:TEXT_LIMIT],
        message_user_name=author,
    )


_ALLOWED_CONTROLS = chr(9) + chr(10) + chr(13) + chr(11) + chr(12)  # 공백처럼 정리되는 제어문자


def _reject_controls(code: str, *values: str | None) -> None:
    """NUL 을 포함한 제어문자(C0/C1, 탭·개행 제외)가 있으면 DB 를 부르기 전에 422. 값은 응답·로그에 싣지 않는다."""
    for value in values:
        if value and any(
            unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROLS for c in value
        ):
            raise ApiError(422, code, "사용할 수 없는 문자가 들어 있어요")


def _title(value: str) -> str:
    _reject_controls("invalid_title", value)
    title = " ".join(value.split())
    visible = "".join(c for c in title if unicodedata.category(c) != "Cf").strip()
    if not visible or len(title) > TITLE_LIMIT:
        raise ApiError(422, "invalid_title", f"제목은 1~{TITLE_LIMIT}자로 적어 주세요")
    return title


def list_links(
    db: Session,
    user: User,
    group_id: str,
    room_id: str | None,
    kind: str | None,
    target_id: str | None,
    limit: int,
) -> LinksOut:
    _reject_controls("invalid_query", room_id, target_id)
    room = resolve_room(db, user, group_id, room_id)
    rows = lrepo.link_rows(db, room.id, limit, kind, target_id)
    return LinksOut(items=[_out(*row) for row in rows])


def create(db: Session, user: User, group_id: str, body: LinkCreate) -> tuple[LinkOut, bool]:
    """(연결, 새로 만들었는지). 이미 있으면 기존 연결과 False."""
    _check_rate(user.id)
    title = _title(body.title)
    _reject_controls("invalid_query", body.room_id, body.target_id)
    room = resolve_room(db, user, group_id, body.room_id)
    ensure_can_send(room)  # 상대가 나간 읽기 전용 방에는 새 연결을 만들 수 없다(삭제는 허용)
    found = repo.get_in_room(db, room, body.message_id)
    if found is None:
        raise bad_request("invalid_message", "이 대화방의 메시지가 아니에요")
    message, author = found
    if not message.text.strip() or repo.attachments_for(db, [message.id]):
        raise bad_request("invalid_message", "글자가 있는 메시지만 연결할 수 있어요")
    if body.kind == "todo" and todo_repo.get(db, group_id, body.target_id) is None:
        raise bad_request("invalid_target", "연결할 할 일을 찾을 수 없어요")
    at_time = time.fromisoformat(body.time) if body.time else None

    lrepo.lock_room(
        db, room.id
    )  # 같은 방의 연결 변경을 직렬화(개수 제한이 겹친 요청에 뚫리지 않게)
    link = lrepo.get_existing(db, room.id, message.id, body.kind, body.target_id)
    created = link is None
    if created:
        if lrepo.count_in_room(db, room.id) >= lrepo.MAX_LINKS:
            raise bad_request("too_many_links", "이 대화방의 연결이 너무 많아요")
        link = lrepo.add_link(
            db,
            group_id,
            room.id,
            message.id,
            body.kind,
            body.target_id,
            title,
            body.date,
            at_time,
            user.id,
        )
        if link is None:  # 겹친 요청이 먼저 만들었다(유니크 충돌)
            created = False
            link = lrepo.get_existing(db, room.id, message.id, body.kind, body.target_id)
    if link is None:  # 겹친 요청이 만든 직후 지워진 드문 경우
        raise ApiError(409, "link_changed", "연결 상태가 바뀌었어요. 다시 시도해 주세요")
    creator = lrepo.user_name(db, link.created_by)
    out = _out(
        link, message, creator, author
    )  # commit 전에 만든다(commit 뒤 객체 만료로 다시 조회하지 않게)
    db.commit()
    return out, created


def delete(db: Session, user: User, group_id: str, link_id: str, room_id: str | None) -> None:
    _check_rate(user.id)
    _reject_controls("invalid_query", link_id, room_id)
    room = resolve_room(db, user, group_id, room_id)
    lrepo.lock_room(
        db, room.id
    )  # 생성과 같은 방 잠금 아래에서 확인·삭제(이미 지워진 연결을 돌려주는 경쟁 방지)
    link = lrepo.get_in_room(db, room.id, link_id)
    if link is None:
        raise not_found("연결")
    if link.created_by != user.id:
        raise ApiError(403, "forbidden", "연결을 만든 사람만 지울 수 있어요")
    lrepo.delete_link(db, room.id, link_id)
    db.commit()
