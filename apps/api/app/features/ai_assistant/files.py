"""올린 파일의 뒷처리: 원본 보관 → 전처리(OCR·가리기·분류·사진 설명) → knowledge 저장.

업로드 요청은 파일을 받자마자 `received` 로 응답하고, 이 모듈의 `process_file` 은 응답이 나간 뒤 백그라운드에서
돈다(OCR·이미지 모델이 몇 초에서 1분 넘게 걸리기 때문). 처리 상태는 `photos.status` 에 적고, 저장된 knowledge
기록의 id 는 파일 id 와 같게 둬서 DB 구조를 바꾸지 않고 둘을 잇는다.
"""

import logging
import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.shared.db import SessionLocal

from . import repository as repo
from .ingest import service as ingest_service
from .ingest.caption import Captioner, default_captioner
from .knowledge import from_ingest
from .knowledge import service as knowledge_service
from .knowledge.repository import get_item
from .schemas import FileStatusOut

logger = logging.getLogger(__name__)

# 한 번에 처리하는 파일 수(OCR 은 CPU, 이미지 모델은 GPU 를 쓴다). 넘치면 순서를 기다린다.
_SLOTS = threading.BoundedSemaphore(2)

MESSAGES = {
    "received": "읽는 중이에요",
    "analyzed": "저장했어요",
    "needs_review": "저장했지만 확인이 필요해요(글자가 흐리거나 종류가 확실하지 않아요)",
    "failed": "파일을 읽지 못했어요. 지원하지 않는 형식이거나 파일이 깨졌을 수 있어요",
}


@dataclass
class Processors:
    """전처리에 끼우는 구성 요소. 비워 두면 기본 구현(RapidOCR, 로컬 Ollama)을 쓰고, 테스트는 가짜를 끼운다."""

    ocr: object | None = None
    llm: object | None = None
    jev: object | None = None
    faces: object | None = None
    captioner: Captioner | None = None
    default_captioner: bool = True


processors = Processors()


def process_file(photo_id: str, group_id: str, user_id: str, data: bytes, filename: str) -> None:
    """전처리해서 knowledge 에 넣고 `photos.status` 를 바꾼다. 어떤 실패도 서버를 멈추지 않는다."""
    status = "failed"
    with _SLOTS:
        try:
            captioner = processors.captioner
            if captioner is None and processors.default_captioner:
                captioner = default_captioner()
            result = ingest_service.ingest_file(
                group_id,
                data,
                filename,
                ocr=processors.ocr,
                llm=processors.llm,
                jev=processors.jev,
                faces=processors.faces,
                captioner=captioner,
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
    return out


def _describe(body_md: str) -> str | None:
    """상태 화면에 보일 한두 문장: 자동 설명이 있으면 그것, 없으면 본문 첫 줄."""
    plain = []
    for line in body_md.splitlines()[2:]:
        if line.startswith("- 자동 설명:"):
            return line.removeprefix("- 자동 설명:").split("(자동으로")[0].strip()[:120] or None
        if line.strip() and not line.startswith("- ") and not line.startswith("[읽지"):
            plain.append(line.strip())
    return plain[0][:120] if plain else None
