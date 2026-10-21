import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.errors import bad_request
from app.shared.llm import client as llm

from . import repository as repo
from .models import Photo
from .schemas import ChatOut

SYSTEM_PROMPT = (
    "당신은 가족 비서 '가비'입니다. 멀리 사는 가족, 특히 부모님의 건강·일정·생활비를 돌보는 일을 돕습니다. "
    "짧고 따뜻한 한국어로 답하고, 모르는 것은 모른다고 말하세요. 의료 진단은 하지 않습니다."
)
FALLBACK_REPLY = (
    "지금은 AI 연결이 꺼져 있어서 기본 안내만 드려요. 일정, 가계, 돌봄 탭에서 기록을 확인해 보세요."
)
ALLOWED_TYPES = {"image/jpeg", "image/png"}
MAX_BYTES = 25 * 1024 * 1024


def chat(message: str) -> ChatOut:
    # TODO: 가족의 일정·지출·돌봄 기록을 검색해서 답에 넣는다(원본의 capture/qa 참고)
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
