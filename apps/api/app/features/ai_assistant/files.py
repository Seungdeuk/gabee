"""올린 파일의 뒷처리: 원본 보관 → 전처리(OCR·가리기·분류) → knowledge 저장.

업로드 요청은 파일을 받자마자 `received` 로 응답하고, 이 모듈의 `process_file` 은 응답이 나간 뒤 백그라운드에서
돈다(OCR 이 몇 초에서 1분 넘게 걸리기 때문). 처리 상태는 `photos.status` 에 적고, 저장된 knowledge
기록의 id 는 파일 id 와 같게 둬서 DB 구조를 바꾸지 않고 둘을 잇는다.
"""

import logging
import mimetypes
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.db import SessionLocal
from app.shared.errors import ApiError

from . import repository as repo
from .ingest import converters, masking
from .ingest import service as ingest_service
from .ingest.raw_store import LocalRawStore
from .knowledge import from_ingest
from .knowledge import service as knowledge_service
from .knowledge.chunking import DOUBT_MARK
from .knowledge.repository import delete_item as knowledge_delete
from .knowledge.repository import get_item, path_in_use
from .schemas import FileStatusOut

logger = logging.getLogger(__name__)

# 한 번에 처리하는 파일 수(OCR 은 CPU 를 쓴다). 넘치면 순서를 기다린다.
_SLOTS = threading.BoundedSemaphore(2)

# 처리 도중 서버가 꺼지면 received 로 영영 남으므로, 이 시간이 지나도록 끝나지 않은 파일은 실패로 본다
STUCK_AFTER = timedelta(minutes=15)

MESSAGES = {
    "received": "읽는 중이에요",
    "analyzed": "저장했어요",
    "needs_review": "저장했지만 확인이 필요해요(글자가 흐리거나 종류가 확실하지 않아요)",
    "failed": "파일을 읽지 못했어요. 지원하지 않는 형식이거나 파일이 깨졌을 수 있어요",
}


@dataclass
class Processors:
    """전처리에 끼우는 구성 요소. 비워 두면 기본 구현(RapidOCR)을 쓰고, 테스트는 가짜를 끼운다."""

    ocr: object | None = None
    jev: object | None = None


processors = Processors()


def process_file(photo_id: str, group_id: str, user_id: str, data: bytes, filename: str) -> None:
    """전처리해서 knowledge 에 넣고 `photos.status` 를 바꾼다. 어떤 실패도 서버를 멈추지 않는다."""
    status = "failed"
    with _SLOTS:
        try:
            result = ingest_service.ingest_file(
                group_id,
                data,
                filename,
                ocr=processors.ocr,
                jev=processors.jev,
            )
            if result.quality.status != "failed":
                with SessionLocal() as db:
                    knowledge_service.ingest(
                        db, group_id, user_id, item_id=photo_id, **from_ingest.to_item(result)
                    )
                status = "needs_review" if from_ingest.needs_review(result) else "analyzed"
        except Exception as e:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
            logger.error("파일 처리에 실패했어요 id=%s 종류=%s", photo_id, type(e).__name__)
            status = "failed"
    with SessionLocal() as db:
        repo.set_status(db, photo_id, status)


def status(db: Session, group_id: str, photo_id: str) -> FileStatusOut | None:
    photo = repo.get_photo(db, group_id, photo_id)
    if photo is None:
        return None
    if photo.status == "received" and _age(photo.created_at) > STUCK_AFTER:
        repo.set_status(db, photo.id, "failed")
        photo.status = "failed"
    out = FileStatusOut(
        id=photo.id,
        filename=photo.filename,
        size=photo.size,
        status=photo.status,
        message=MESSAGES.get(photo.status),
    )
    item = (
        get_item(db, group_id, photo_id) if photo.status in ("analyzed", "needs_review") else None
    )
    if item is not None:
        out.title, out.kind_label = item.title, item.kind_label
        out.description = _describe(item.body_md)
        out.doubts = _doubts(item.body_md)
        out.needs_description = from_ingest.needs_description(item.kind_label, item.body_md)
    return out


def set_description(db: Session, group_id: str, photo_id: str, text: str) -> FileStatusOut | None:
    """사진에 사용자가 쓴 한 줄 설명을 저장하고(이미 있으면 덮어쓴다) 검색 조각을 다시 만든다.

    이 가족의 파일이 아니거나 없으면 None, 사진이 아니면 409. 설명도 사용자 입력이라 개인정보를 가린다."""
    item = get_item(db, group_id, photo_id)
    if repo.get_photo(db, group_id, photo_id) is None or item is None:
        return None
    if item.kind_label != from_ingest.PHOTO_KIND:
        raise ApiError(409, "not_a_photo", "사진에만 설명을 달 수 있어요")
    text = " ".join(masking.mask_text(text).split())[: from_ingest.DESCRIPTION_MAX]
    changes = {"body_md": from_ingest.with_description(item.body_md, text)}
    before = from_ingest.current_description(item.body_md)
    if from_ingest.is_default_title(item.title, item.kind_label) or (
        before and item.title == before[:50]
    ):
        changes["title"] = text[:50]  # 제목이 기본값이거나 이전 설명이면 새 설명이 제목이 된다
    knowledge_service.update_item(db, group_id, photo_id, changes)
    return status(db, group_id, photo_id)


def original(db: Session, group_id: str, photo_id: str) -> tuple[bytes, str, str] | None:
    """올린 원본 파일 (바이트, 파일 이름, content_type). 이 가족의 것이 아니거나 없으면 None."""
    photo = repo.get_photo(db, group_id, photo_id)
    item = get_item(db, group_id, photo_id)
    if photo is None or item is None or not item.source_path:
        return None
    try:
        data = LocalRawStore().get_for_group(group_id, item.source_path)
    except (ValueError, OSError):
        return None
    ctype = mimetypes.guess_type(item.source_path)[0] or "application/octet-stream"
    return data, photo.filename, ctype


def delete_record(db: Session, group_id: str, item_id: str) -> bool:
    """기록(읽어 낸 글·검색 조각·올린 파일 정보)과 서버에 둔 원본·화면용 사본을 지운다. 되돌릴 수 없다.

    같은 파일을 두 번 올려 같은 원본을 가리키는 기록이 남아 있으면 원본 파일은 그대로 둔다.
    이 가족의 기록이 아니거나 없으면 False."""
    item = get_item(db, group_id, item_id)
    if item is None:
        return False
    path = item.source_path
    knowledge_delete(db, item)
    repo.delete_photo(db, item_id)
    if path and not path_in_use(db, group_id, path):
        store = LocalRawStore()
        stem = path.rsplit(".", 1)[0]
        for ref in (path, f"{stem}.display.webp"):
            try:
                store.delete_for_group(group_id, ref)
            except (ValueError, OSError):  # 파일이 이미 없거나 못 지워도 기록 삭제는 끝낸다
                logger.warning("원본 파일을 지우지 못했어요 id=%s", item_id)
    return True


def original_pdf_pages(db: Session, group_id: str, photo_id: str) -> int | None:
    """원본이 PDF 면 앱에서 보여 줄 쪽 수, PDF 가 아니거나 이 가족의 파일이 아니면 None."""
    found = original(db, group_id, photo_id)
    if found is None or found[2] != "application/pdf":
        return None
    try:
        return converters.pdf_page_count(found[0])
    except converters.BrokenFile:
        return None


def original_pdf_page(db: Session, group_id: str, photo_id: str, page: int) -> bytes | None:
    """원본 PDF 의 한 쪽(1부터)을 JPEG 로 그린 것. 없는 쪽이거나 이 가족의 파일이 아니면 None."""
    found = original(db, group_id, photo_id)
    if found is None or found[2] != "application/pdf":
        return None
    try:
        return converters.pdf_page_jpeg(found[0], page - 1)
    except (IndexError, converters.BrokenFile):
        return None


def _doubts(body_md: str) -> list[str]:
    """[불확실] 이 붙은 줄(표시는 뺀 글)."""
    return [
        ln.removesuffix(DOUBT_MARK).strip()
        for ln in body_md.splitlines()
        if ln.rstrip().endswith(DOUBT_MARK)
    ]


def _describe(body_md: str) -> str | None:
    """상태 화면에 보일 한두 문장: 사용자가 단 설명이 있으면 그것, 없으면 본문 첫 줄."""
    plain = []
    for line in body_md.splitlines()[2:]:
        if line.startswith(from_ingest.DESCRIPTION_LABEL):
            return line.removeprefix(from_ingest.DESCRIPTION_LABEL).strip()[:120] or None
        if line.strip() and not line.startswith("- ") and not line.startswith("[읽지"):
            plain.append(line.strip())
    return plain[0][:120] if plain else None


def _age(created: datetime) -> timedelta:
    created = created if created.tzinfo else created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created
