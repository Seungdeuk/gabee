"""가족 소통 채팅방 문서·사진은 **실제 Claude 가리기**(`INGEST_LLM_MASK`)를 거칠 수 없으면 AI 문서함에 등록하지 않는다(ADR 0024, 사용자 승인 2026-11-23).

결함(재현 시험 → 정식 회귀 시험): `INGEST_LLM_MASK=false` 이면 동의가 켜져 있어도 로컬 규칙(주민등록번호 등만 가림)으로 대신해 등록했고, 그 기록은
동의 시각 필터를 통과해 @가비 검색으로 이름·주소·전화번호가 외부 AI 에 전송됐다. 이제 `require_external`(채팅 처리 목적)이면 `masking_unavailable` 로
실패시키고(서비스 `_mask` + `preprocess` 시작) 라이브러리 진입(`library`)과 직접 저장 라우트에서도 외부 호출 전에 멈춘다.
메인 AI 직접 업로드(`require_external=False`)는 기존 정책 그대로다. Claude 는 대역(실제 호출 없음), 개인정보는 합성값이다."""

# ruff: noqa: F811  (다른 시험 모듈의 픽스처를 가져와 쓴다: pytest 픽스처 주입 방식)
import pytest
from sqlalchemy import func, select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import llm_ingest, siglip_margin
from app.features.ai_assistant.ingest import service as ingest_service
from app.features.ai_assistant.knowledge.models import KnowledgeChunk, KnowledgeItem
from app.features.ai_assistant.tests.test_consent_ingest_flow import (  # noqa: F401  (픽스처·도우미 재사용)
    FakeScorer,
    _assistant_sees,
    _chat_file,
    _check,
    _consent,
    _isolated,
    _items,
    _main_upload,
    _revoker,
    _send_photo,
    _status,
    claude,
    family,
    pdf,
)
from app.features.family_chat.models import MessageAttachment
from app.shared.config import settings
from app.shared.db import SessionLocal

TXT = "Family meeting notice\nPlace 152 Teheran-ro Gangnam\nContact Younghee Lee 010-9999-8888\nPlease reply soon"
PDF_TEXT = "Family meeting notice Place 152 Teheran-ro Contact Younghee Lee 010-9999-8888"
LEAK = ("Teheran-ro", "Younghee")
QUESTION = "Where is the family meeting place and contact?"


@pytest.fixture
def masking_claude(claude, monkeypatch):
    """Claude 가리기 대역: 주소·이름을 [가림] 으로 바꾼다. 읽기·가리기 호출 횟수를 센다."""

    def mask(text, family=None):
        claude.calls["mask"] += 1
        return text.replace("Teheran-ro", "[가림]").replace("Younghee", "[가림]"), {"x": 1}, "none"

    def ocr_pdf(data):
        claude.calls["ocr_pdf"] += 1
        claude._read_done()
        return PDF_TEXT, None

    def ocr_image(image):
        claude.calls["ocr_image"] += 1
        claude._read_done()
        from app.shared.llm import doc_ai

        return doc_ai.OcrOut(TXT, False, 0, 0)

    monkeypatch.setattr(llm_ingest, "mask", mask)
    monkeypatch.setattr(llm_ingest, "ocr_pdf", ocr_pdf)
    monkeypatch.setattr(llm_ingest, "ocr_image", ocr_image)
    return claude


def _chunk_count(group_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.item_id)
            .where(KnowledgeItem.group_id == group_id)
        )


def _attachments(group_id: str) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(MessageAttachment)
            .where(MessageAttachment.group_id == group_id)
        )


def _upload(client, headers, kind):
    if kind == "txt":
        return _chat_file(client, headers, "m.txt", TXT.encode(), "text/plain")
    return _chat_file(client, headers, "m.pdf", pdf([PDF_TEXT]), "application/pdf")


# ---------- 1·2·3·9. 문서 × MASK × OCR ----------


@pytest.mark.parametrize("ocr", [True, False])
@pytest.mark.parametrize("mask", [True, False])
@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_chat_document_registration_requires_real_claude_masking(
    client, family, masking_claude, monkeypatch, kind, mask, ocr
):
    a, _, group = family  # 가족 AI 동의 ON
    monkeypatch.setattr(settings, "ingest_llm_mask", mask)
    monkeypatch.setattr(settings, "ingest_llm_ocr", ocr)
    msg = _upload(client, a, kind)
    assert msg["id"]  # 채팅 메시지는 항상 간다
    assert _attachments(group["id"]) == 1  # 원본 첨부도 그대로 남는다
    seen = _assistant_sees(client, a, monkeypatch, QUESTION)
    if mask:  # 대조군: 가리기가 켜져 있으면 정상 등록되고 개인정보는 가려져 나간다
        assert len(_items(group["id"])) == 1 and masking_claude.calls["mask"] == 1
        assert [w for w in LEAK if w in seen] == []
    else:
        assert _items(group["id"]) == []  # 등록 0건
        assert _chunk_count(group["id"]) == 0  # 검색 조각도 0건(부분 등록 없음)
        assert masking_claude.total() == 0, masking_claude.calls  # 읽기(OCR)도 시작하지 않는다
        assert [w for w in LEAK if w in seen] == []  # @가비 도구 결과에 개인정보가 없다


def test_a_chat_document_can_be_registered_by_uploading_again_after_masking_is_back(
    client, family, masking_claude, monkeypatch
):
    """실패 상태가 재시도 구조와 호환된다: 자동 재시도(llm_unavailable 만 재시도)는 하지 않고, 가리기를 되살린 뒤 다시 올리면 정상 등록된다."""
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    _upload(client, a, "txt")
    assert _items(group["id"]) == []
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    _chat_file(client, a, "again.txt", (TXT + " again").encode(), "text/plain")
    assert len(_items(group["id"])) == 1 and _chunk_count(group["id"]) > 0


# ---------- 서비스 계층(이중 방어 1: `_mask` 와 preprocess 시작) ----------


def test_service_fails_closed_for_the_chat_purpose_before_any_external_call(
    masking_claude, monkeypatch
):
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    r = ingest_service.preprocess(pdf([PDF_TEXT]), "m.pdf", external=True, require_external=True)
    assert r.quality.status == "failed" and r.quality.error == "masking_unavailable"
    assert r.content.text == "" and masking_claude.total() == 0


def test_mask_itself_refuses_a_local_fallback_for_the_chat_purpose(monkeypatch):
    """preprocess 시작 검사를 거치지 않고 `_mask` 를 바로 불러도 막힌다(두 번째 방어)."""
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    with pytest.raises(ingest_service.MaskingUnavailable):
        ingest_service._mask(TXT, None, True, None, True)
    # 메인 AI(require_external=False)는 기존대로 로컬 규칙으로 가린다
    text, _ = ingest_service._mask(TXT, None, True, None, False)
    assert "Teheran-ro" in text  # 이름·주소는 로컬 규칙이 가리지 않는다(기존 동작, 메인 AI 정책)


# ---------- 라이브러리 진입(이중 방어 2: 외부 호출 시작 전) ----------


def test_library_stops_before_receiving_or_processing_when_masking_is_off(
    client, family, masking_claude, monkeypatch
):
    a, _, group = family
    uid = client.get("/family-group/me", headers=a).json()["id"]

    entered = []

    def spy(*args, **kwargs):  # register_* 는 예외를 삼키므로 예외 대신 호출 기록으로 확인한다
        entered.append(args[:1])
        return "failed", False

    def receive_spy(*args, **kwargs):
        entered.append("receive_file")
        raise RuntimeError("stop")

    monkeypatch.setattr(files, "process_file", spy)
    monkeypatch.setattr(library.service, "receive_file", receive_spy)
    # 첨부가 있는 것처럼 만들어, 마스킹 검사가 없다면 받기·처리까지 가도록 한다(검사 앞에서 우연히 멈추는 시험이 되지 않게)
    monkeypatch.setattr(library.chat_library, "attachment_exists", lambda *a: True)
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    library.register_chat_document(group["id"], uid, "att-doc", "m.txt", "text/plain", TXT.encode())
    library.register_chat_photo(group["id"], uid, "att-photo", b"x", forced=True)
    assert entered == ["receive_file", "receive_file"]  # 대조군: 가리기가 켜져 있으면 받기까지 간다
    entered.clear()
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    library.register_chat_document(group["id"], uid, "att-doc", "m.txt", "text/plain", TXT.encode())
    library.register_chat_photo(group["id"], uid, "att-photo", b"x", forced=True)
    assert entered == [], "가리기가 꺼져 있으면 파일을 받지도 처리하지도 않는다"
    assert _items(group["id"]) == [] and masking_claude.total() == 0


# ---------- 7. 사진 자동 등록·수동 저장 ----------


def test_photo_auto_registration_requires_masking(client, family, masking_claude, monkeypatch):
    a, _, group = family
    siglip_margin.set_scorer(FakeScorer(margin=8.0))
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    _send_photo(client, a, (200, 200, 200))  # 대조군: 가리기가 켜져 있으면 등록
    assert len(_items(group["id"])) == 1 and masking_claude.calls["mask"] == 1
    masking_claude.reset()
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    att = _send_photo(client, a, (100, 100, 100))
    assert len(_items(group["id"])) == 1  # 늘지 않는다
    assert masking_claude.total() == 0
    assert _check(att).status != "document"  # 판별 상태도 바꾸지 않는다(사진은 채팅에 남는다)
    assert _chunk_count(group["id"]) == _chunk_count_for_one_item(group["id"])


def _chunk_count_for_one_item(group_id: str) -> int:
    with SessionLocal() as db:
        first = db.scalars(select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)).first()
        return db.scalar(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.item_id == first.id)
        )


def test_manual_save_to_library_is_blocked_while_masking_is_off(
    client, family, masking_claude, monkeypatch
):
    a, _, group = family
    siglip_margin.set_scorer(FakeScorer(margin=0.0))
    att = _send_photo(client, a)
    assert _check(att).status == "unsure"
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 503 and r.json()["code"] == "masking_unavailable", r.text
    assert _items(group["id"]) == [] and masking_claude.total() == 0
    assert _check(att).status == "unsure"  # 상태도 바뀌지 않는다
    monkeypatch.setattr(settings, "ingest_llm_mask", True)  # 대조군: 되살리면 저장된다
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 200 and r.json() == {"status": "queued"}
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]


# ---------- 5. 동의 OFF → 외부 전송 0회 ----------


@pytest.mark.parametrize("mask", [True, False])
@pytest.mark.parametrize("kind", ["txt", "pdf"])
def test_without_consent_nothing_is_sent_whatever_the_masking_setting(
    client, family, masking_claude, monkeypatch, kind, mask
):
    a, _, group = family
    _consent(client, a, False)
    monkeypatch.setattr(settings, "ingest_llm_mask", mask)
    _upload(client, a, kind)
    assert _items(group["id"]) == [] and masking_claude.total() == 0


# ---------- 6. 메인 AI 직접 업로드: 기존 동작 유지 ----------


@pytest.mark.parametrize("family_consents", [True, False])
def test_main_ai_direct_upload_is_unaffected_by_the_chat_masking_rule(
    client, family, masking_claude, monkeypatch, family_consents
):
    a, _, group = family
    _consent(client, a, family_consents)
    fid = _main_upload(
        client, a, "m.txt", TXT.encode(), "text/plain"
    )  # 가리기 ON: Claude 가 가린다
    assert _status(client, a, fid) in ("analyzed", "needs_review")
    assert masking_claude.calls["mask"] >= 1
    monkeypatch.setattr(
        settings, "ingest_llm_mask", False
    )  # 운영자가 끈 경우 기존 정책(로컬 규칙)대로 처리한다
    fid2 = _main_upload(client, a, "m2.txt", (TXT + " 2").encode(), "text/plain")
    assert _status(client, a, fid2) in ("analyzed", "needs_review")
    assert len(_items(group["id"])) == 2


# ---------- 8. 처리 도중 동의 철회(기존 차단 유지) ----------


def test_consent_revoked_mid_flight_still_registers_nothing_with_masking_on(
    client, family, masking_claude
):
    a, _, group = family
    masking_claude.after_read = _revoker(client, a, group["id"])
    _upload(client, a, "pdf")
    assert masking_claude.calls["ocr_pdf"] == 1 and masking_claude.calls["mask"] == 0
    assert _items(group["id"]) == [] and _chunk_count(group["id"]) == 0
