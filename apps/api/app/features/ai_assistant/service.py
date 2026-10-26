import uuid
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request
from app.shared.llm import client as llm
from app.shared.llm.agent_chat import to_out as to_proposal_out

from . import repository as repo
from .knowledge import rag_chat
from .models import Photo
from .schemas import ChatOut, ChatSource

SYSTEM_PROMPT = (
    "당신은 가족 비서 '가비'입니다. 멀리 사는 가족, 특히 부모님의 건강·일정·생활비를 돌보는 일을 돕습니다. "
    "짧고 따뜻한 한국어로 답하고, 모르는 것은 모른다고 말하세요. 의료 진단은 하지 않습니다."
)
FALLBACK_REPLY = (
    "지금은 AI 연결이 꺼져 있어서 기본 안내만 드려요. 일정, 가계, 돌봄 탭에서 기록을 확인해 보세요."
)
DAILY_LIMIT = 100  # 사용자 한 명이 하루에 부를 수 있는 AI 답변 수
_calls: dict[str, tuple[date, int]] = {}
ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 25 * 1024 * 1024


def _check_daily_limit(user_id: str) -> None:
    """사용자별 하루 AI 호출 한도(서버 프로세스 메모리 기준이라 재시작하면 0 으로 돌아간다)."""
    today = date.today()
    day, count = _calls.get(user_id, (today, 0))
    if day != today:
        count = 0
    if count >= DAILY_LIMIT:
        raise ApiError(
            429,
            "daily_limit",
            "오늘은 가비에게 물어볼 수 있는 횟수를 모두 썼어요. 내일 다시 물어봐 주세요",
        )
    _calls[user_id] = (today, count + 1)


def chat(
    db: Session,
    group_id: str | None,
    user_id: str,
    message: str,
    history: list[dict] | None = None,
    user: User | None = None,
) -> ChatOut:
    """가족 그룹이 있으면 저장된 기록(knowledge)을 검색해서 근거로 답한다. 그룹이 없으면 기록 없이 답한다.

    TODO: 일정·지출·돌봄 기록도 검색 대상에 넣는다(원본의 capture/qa 참고)."""
    if group_id:
        if settings.anthropic_api_key:
            _check_daily_limit(user_id)
        r = rag_chat.ask(db, group_id, message, history=history, user=user)
        sources = [
            ChatSource(
                n=s["n"], title=s["title"], item_id=s["item_id"], source_path=s["source_path"]
            )
            for s in r.sources
        ]
        return ChatOut(
            reply=r.answer, source=r.source, sources=sources, proposals=to_proposal_out(r.proposals)
        )
    try:
        return ChatOut(reply=llm.complete(message, system=SYSTEM_PROMPT), source="ai")
    except llm.LLMUnavailable:
        return ChatOut(reply=FALLBACK_REPLY, source="fallback")


def save_photo(
    db: Session, group_id: str, user_id: str, filename: str, content_type: str, data: bytes
) -> Photo:
    if content_type not in ALLOWED_TYPES:
        raise bad_request("unsupported_type", "JPEG 또는 PNG 사진만 올릴 수 있어요")
    if not data:
        raise bad_request("empty_file", "사진 데이터가 비어 있어요")
    if len(data) > MAX_BYTES:
        raise bad_request("too_large", "사진이 너무 커요(25MB 이하)")
    photo_id = uuid.uuid4().hex[:12]
    folder = Path(settings.data_dir) / "photos"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{photo_id}{'.png' if content_type == 'image/png' else '.jpg'}").write_bytes(data)
    return repo.add(
        db,
        Photo(
            id=photo_id,
            group_id=group_id,
            uploaded_by=user_id,
            filename=Path(filename or "photo").name[:200],
            content_type=content_type,
            size=len(data),
        ),
    )


def receive_file(
    db: Session, group_id: str, user_id: str, filename: str, content_type: str, data: bytes
) -> Photo:
    """어떤 종류의 파일이든 받아서 기록(`received`)만 남긴다. 읽고 분류하는 일은 `files.process_file` 이 뒤에서 한다."""
    if not data:
        raise bad_request("empty_file", "파일이 비어 있어요")
    if len(data) > MAX_BYTES:
        raise bad_request("too_large", "파일이 너무 커요(25MB 이하)")
    return repo.add(
        db,
        Photo(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            uploaded_by=user_id,
            filename=Path(filename or "file").name[:200],
            content_type=(content_type or "application/octet-stream")[:60],
            size=len(data),
        ),
    )
