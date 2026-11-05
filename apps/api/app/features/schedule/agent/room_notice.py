"""가족 채팅방 @가비 의 확인 카드를 눌러 공유 등록을 마쳤을 때, 결과를 가비 이름으로 방에 알린다.

확인 질문("공유해서 등록할까요?")은 버튼이 없는 다른 구성원에게 열린 질문으로 남아서 방에 올리지 않는다. 대신 질문한 사람이
공유 등록을 확인하면 그 결과만 올린다. 문장은 실행된 결과(제목·날짜·시간·공유 인원)로 서버가 만들고 사용자가 보낸 글은 쓰지 않는다.
나만 등록·취소·이미 있던 일정이면 올리지 않는다."""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.shared import room_assistant

from .schemas import AgentResponse, ConfirmRequest

logger = logging.getLogger(__name__)

TITLE_MAX = (
    30  # 알림에 넣는 제목 길이. 확인 요청의 초안 제목은 클라이언트가 보낸 값이라 짧게 자른다
)


def _short_title(title: object) -> str:
    """제목을 한 줄로 합치고(줄바꿈·연속 공백 제거) 짧게 자른다. 가비 이름으로 원하는 글을 올릴 수 없게 하는 안전장치다."""
    one_line = " ".join(str(title or "").split())
    return one_line if len(one_line) <= TITLE_MAX else one_line[: TITLE_MAX - 1].rstrip() + "…"


def notice_text(body: ConfirmRequest, response: AgentResponse) -> str | None:
    """방에 알릴 문장. 알릴 일이 아니면 None."""
    if body.action.type != "register" or not body.share:
        return None
    card = next((c for c in response.cards if c.type == "registered"), None)
    if card is None or card.data.get("already"):
        return None
    shared = int(card.data.get("shared") or 0)
    if shared <= 0:
        return None
    when = ""
    try:
        when = f"{date.fromisoformat(card.data['date']):%m/%d}"
    except (KeyError, ValueError):
        pass
    if card.data.get("start_time"):
        when = f"{when} {card.data['start_time']}".strip()
    where = f"{when}에 " if when else ""
    title = _short_title(card.data.get("title"))
    return f"'{title}' 일정을 {where}등록하고 가족 {shared}명에게 공유했어요."


def post_if_needed(
    db: Session, group_id: str, body: ConfirmRequest, response: AgentResponse
) -> None:
    """`post_to_room` 일 때만 알린다. 알림이 실패해도 이미 만든 일정과 응답은 그대로다."""
    if not body.post_to_room:
        return
    text = notice_text(body, response)
    if not text:
        return
    try:
        room_assistant.post(db, group_id, text)
    except Exception as exc:
        logger.warning("room notice failed error=%s", type(exc).__name__)
