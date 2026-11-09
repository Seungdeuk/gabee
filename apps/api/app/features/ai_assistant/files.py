"""올린 파일의 뒷처리: 원본 보관 → 전처리(OCR·가리기·분류) → knowledge 저장.

업로드 요청은 파일을 받자마자 `received` 로 응답하고, 이 모듈의 `process_file` 은 응답이 나간 뒤 백그라운드에서
돈다(OCR 이 몇 초에서 1분 넘게 걸리기 때문). 처리 상태는 `photos.status` 에 적고, 저장된 knowledge
기록의 id 는 파일 id 와 같게 둬서 DB 구조를 바꾸지 않고 둘을 잇는다.
"""

import hashlib
import logging
import mimetypes
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import Group, GroupMember
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.notifications import notify

from . import family_names, reminders
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


def _notify_document(db: Session, group_id: str, user_id: str, item) -> None:
    """가족 문서함에 새 문서가 저장되면 올린 사람을 뺀 가족에게 고정 문구로 알린다. 문서 제목·내용은 담지 않고, 민감 문서는 존재도 알리지 않는다.
    알림이 실패해도 문서 저장에는 영향이 없다(notify 가 삼킨다)."""
    if item.sensitivity == "sensitive":
        return
    members = list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group_id)))
    notify(
        db,
        group_id=group_id,
        kind="ai_record",
        event="document_added",
        recipients=members,
        title="가족 문서함에 새 문서가 올라왔어요",
        target_type="knowledge_item",
        target_id=item.id,
        actor_user_id=user_id,
    )
    db.commit()


def process_file(
    photo_id: str,
    group_id: str,
    user_id: str,
    data: bytes,
    filename: str,
    source_attachment_id: str | None = None,
    keep_photo: bool = False,
) -> None:
    """전처리해서 knowledge 에 넣고 `photos.status` 를 바꾼다. 어떤 실패도 서버를 멈추지 않는다.
    `keep_photo` 는 채팅 사진을 사용자가 직접 "문서로 저장"한 경우다: 글자가 거의 없어 "사진" 기록이 돼도 문서함에 남긴다.

    Claude 연결이 잠깐 안 돼서 실패(`llm_unavailable`)했으면 기다렸다가 같은 파일을 다시 처리한다(원본 바이트는 이미 메모리에 있다).
    깨진 파일·지원 안 하는 형식은 다시 해도 같으므로 다시 하지 않는다. 기다리는 동안은 처리 칸을 비워 다른 파일이 지나가게 한다."""
    status = "failed"
    for attempt in range(settings.ingest_retry_max + 1):
        if attempt:
            time.sleep(settings.ingest_retry_wait_seconds * attempt)
        with _SLOTS:
            status, retry = _process_once(
                photo_id, group_id, user_id, data, filename, source_attachment_id, keep_photo
            )
        if not retry:
            break
        logger.warning(
            "Claude 연결이 안 돼 파일을 다시 처리해요 id=%s 시도=%d/%d",
            photo_id,
            attempt + 1,
            settings.ingest_retry_max + 1,
        )
    with SessionLocal() as db:
        if source_attachment_id and status == "failed":
            # 채팅 문서는 읽지 못해도(재시도를 다 써도) "실패" 기록과 가리기 전 원본을 남기지 않는다(채팅 파일로는 남아 있다)
            _drop_chat_upload(group_id, photo_id, data)
        else:
            repo.set_status(db, photo_id, status)


def _drop_chat_upload(group_id: str, photo_id: str, data: bytes) -> None:
    """등록하지 않기로 한(민감·실패·중복·지워진) 채팅 문서의 처리 기록(photos)과, 읽는 도중 보관한 원본·사본을 지운다.
    파일은 내용(sha256)으로 찾아서 결과 객체가 없는 실패·예외에서도 정리된다. 다른 기록이 쓰는 원본은 그대로 둔다."""
    with SessionLocal() as db:
        repo.delete_photo(db, photo_id)
        store = LocalRawStore()
        refs = store.refs_for_sha(group_id, hashlib.sha256(data).hexdigest())
        main = [r for r in refs if ".display." not in r]
        if any(path_in_use(db, group_id, r) for r in main):
            return
        for ref in refs:
            try:
                store.delete_for_group(group_id, ref)
            except (ValueError, OSError):
                logger.warning("원본 파일을 지우지 못했어요 id=%s", photo_id)


def _only_a_bank_account(result) -> bool:
    """통장류(`bankbook`)로 잡힌 문서가 학교·기관의 납부 계좌 안내문인가. 판단은 읽기 단계가 가리기 **전의** 글로 해 둔 값이다
    (통장 사본·이체확인증·거래내역은 통장·받는분·잔액 같은 낱말이 있어 그대로 민감 문서다)."""
    return result.privacy.sensitive == "bankbook" and result.privacy.account_notice


def _plan_reminders(photo_id: str, group_id: str, user_id: str) -> None:
    """저장된 기록에서 챙길 일을 뽑는다(설정이 켜진 경우). 실패해도 파일은 그대로 저장된 상태로 둔다."""
    if not settings.ingest_reminders:
        return
    try:
        with SessionLocal() as db:
            reminders.plan(db, group_id, user_id, photo_id)
    except Exception as e:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("챙길 일을 뽑지 못했어요 id=%s 종류=%s", photo_id, type(e).__name__)


def _process_once(
    photo_id: str,
    group_id: str,
    user_id: str,
    data: bytes,
    filename: str,
    source_attachment_id: str | None = None,
    keep_photo: bool = False,
) -> tuple[str, bool]:
    """한 번 처리한다. (상태, 다시 해 볼 만한 실패인지)"""
    try:
        # 가족 이름은 가리기 전에 자리표시로 바꾼다(분류를 외부 서비스에 맡겨도 실명이 나가지 않는다)
        with SessionLocal() as db:
            family = family_names.FamilyTagger(family_names.load_members(db, group_id))
        result = ingest_service.ingest_file(
            group_id,
            data,
            filename,
            ocr=processors.ocr,
            jev=processors.jev,
            family=family,
        )
        if result.quality.status == "failed":
            retry = result.quality.error == "llm_unavailable"
            if source_attachment_id and not retry:
                _drop_chat_upload(group_id, photo_id, data)
            return "failed", retry
        fields = from_ingest.to_item(result)
        if (
            source_attachment_id
            and not keep_photo
            and fields["kind_label"] == from_ingest.PHOTO_KIND
        ):
            # 문서 사진으로 보고 읽었는데 글자가 거의 없다: 일반 사진은 문서함에 넣지 않는다
            _drop_chat_upload(group_id, photo_id, data)
            return "skipped", False
        if source_attachment_id and _only_a_bank_account(result):
            # 학교 납부 안내처럼 계좌번호만 이유로 통장류로 잡힌 문서(통장 사본이 아니다)는 등록한다. 계좌번호는 읽을 때 이미 가려진다.
            # 분류 이름이 처방전·신분증·통장 같은 민감 종류면 아래 검사가 그대로 제외한다.
            fields["sensitivity"] = None
        if source_attachment_id and knowledge_service.is_sensitive(
            fields["kind_label"], fields.get("sensitivity"), strict=True
        ):
            _drop_chat_upload(
                group_id, photo_id, data
            )  # 민감 문서(처방전·신분증·진단서 등)는 자동 등록하지 않는다
            return "skipped", False
        with SessionLocal() as db:
            try:
                item = knowledge_service.ingest(
                    db,
                    group_id,
                    user_id,
                    item_id=photo_id,
                    source_attachment_id=source_attachment_id,
                    **fields,
                )
            except IntegrityError:  # 같은 채팅 첨부를 다른 요청이 먼저 등록했다
                db.rollback()
                _drop_chat_upload(group_id, photo_id, data)
                return "skipped", False
            if db.get(Group, group_id) is None:
                # 읽는 사이에 가족이 지워졌다(혼자인 소유자가 나감): 방금 저장한 기록과 원본이 주인 없이 남지 않게 되돌린다
                delete_record(db, group_id, photo_id)
                return "skipped", False
            if source_attachment_id and not chat_library.attachment_exists(
                db, group_id, source_attachment_id
            ):
                # 읽는 사이에 채팅 메시지가 지워졌다: 방금 저장한 기록을 되돌린다(지운 메시지의 문서가 문서함에 남지 않게)
                delete_record(db, group_id, photo_id)
                return "skipped", False
            if (
                not source_attachment_id
            ):  # 채팅에 이미 올라온 파일이라 "새 문서" 알림은 한 번 더 보내지 않는다
                try:
                    _notify_document(db, group_id, user_id, item)
                except Exception as e:  # noqa: BLE001  문서는 이미 저장됐다: 알림 실패가 처리 실패로 바뀌지 않게 종류만 적는다
                    db.rollback()
                    logger.warning(
                        "문서 알림에 실패했어요 id=%s 종류=%s", photo_id, type(e).__name__
                    )
        _plan_reminders(photo_id, group_id, user_id)
        return ("needs_review" if from_ingest.needs_review(result) else "analyzed"), False
    except Exception as e:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.error("파일 처리에 실패했어요 id=%s 종류=%s", photo_id, type(e).__name__)
        if source_attachment_id:
            _drop_chat_upload(
                group_id, photo_id, data
            )  # 예외로 끝나도 읽는 도중 보관한 원본이 기록 없이 남지 않게
        return "failed", False


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
        names = family_names.shown_names(family_names.load_members(db, group_id))
        body = family_names.restore(item.body_md, names)  # 자리표시를 현재 이름으로(자르기 전에)
        out.title, out.kind_label = family_names.restore(item.title, names), item.kind_label
        out.description = _describe(body)
        out.doubts = _doubts(body)
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
    # 설명에 쓴 가족 이름도 가리기 전에 자리표시로 바꾼다(저장되는 글에는 실명이 없다)
    tagger = family_names.FamilyTagger(family_names.load_members(db, group_id))
    masked = " ".join(tagger.expand(masking.mask_text(tagger.protect(text))).split())
    text = family_names.clip(masked, from_ingest.DESCRIPTION_MAX)
    changes = {"body_md": from_ingest.with_description(item.body_md, text)}
    before = from_ingest.current_description(item.body_md)
    if from_ingest.is_default_title(item.title, item.kind_label) or (
        before and item.title == family_names.clip(before, 50)
    ):
        changes["title"] = family_names.clip(
            text, 50
        )  # 제목이 기본값이거나 이전 설명이면 새 설명이 제목이 된다
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
