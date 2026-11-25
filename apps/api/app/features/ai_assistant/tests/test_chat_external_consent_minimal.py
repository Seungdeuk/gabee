"""가족 채팅 목적의 처리는 가족 AI 동의가 있을 때만 외부(Claude·Jev)로 보낸다(보안 A, OCR 제거 없이 최소 변경).

계약:
- 동의 OFF → 가족 채팅 문서·사진 등록을 보류하고 외부 호출 0회(채팅 첨부는 그대로, 사진 판별 상태는 로컬 판별대로 남는다).
- 처리 도중 동의 철회 → 그 뒤의 외부 호출은 나가지 않고, 로컬 규칙으로 대신 처리한 결과를 등록하지 않는다.
- 수동 "문서로 저장" → 동의가 없으면 403 `ai_not_enabled`, 판별 상태는 바꾸지 않는다.
- 메인 AI 직접 업로드(관문 범위 밖)는 기존 정책 그대로(동의와 무관하게 외부 호출).
외부 HTTP 는 대역(`httpx.post` 기록기)이라 실제로 나가지 않는다. 데이터는 합성이다. 과거에 저장된 기록이 안전하다는 보장은 하지 않는다."""

import io
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from PIL import Image

from app.features.ai_assistant import library
from app.features.ai_assistant.ingest import llm_ingest, masking
from app.features.ai_assistant.tests.test_chat_library import (  # noqa: F401  (autouse 격리·도우미 재사용)
    _isolated,
    _items,
    _send_file,
)
from app.features.family_chat.models import ChatPhotoCheck
from app.shared.ai_usage import AiGroupSetting
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import consent_gate, jev, transport


class Outbound:
    """외부로 나가려던 HTTP 호출 기록(실제로는 보내지 않는다)."""

    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url, *a, **k):
        self.urls.append(str(url))
        req = httpx.Request("POST", url)
        if "typesafe" in str(url):
            return httpx.Response(200, json={"answers": {"q": {"noul": 0.1}}}, request=req)
        return httpx.Response(
            200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}}, request=req
        )


_REAL_ALLOWED = (
    consent_gate.family_ai_allowed
)  # 폴더 conftest 가 '동의 켜짐'으로 바꿔 두므로 진짜 확인을 붙잡아 둔다


@pytest.fixture(autouse=True)
def _real_consent_check(monkeypatch):
    monkeypatch.setattr(
        consent_gate, "family_ai_allowed", _REAL_ALLOWED
    )  # 이 파일은 실제 동의 확인을 시험한다


@pytest.fixture
def outbound(monkeypatch):
    rec = Outbound()
    monkeypatch.setattr(httpx, "post", rec)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    return rec


def _consent(group_id: str, enabled: bool) -> None:
    with SessionLocal() as db:
        row = db.get(AiGroupSetting, group_id) or AiGroupSetting(group_id=group_id)
        row.enabled = enabled
        db.add(row)
        db.commit()


# ---------- 관문 단위 ----------
def test_inside_a_family_chat_scope_without_consent_nothing_is_sent(client, family, outbound):
    _, _, group = family
    _consent(group["id"], False)
    with consent_gate.family_chat(group["id"]):
        with pytest.raises(consent_gate.ConsentRequired):
            transport.post_messages({"x": 1})
        with pytest.raises(consent_gate.ConsentRequired):
            jev.ask("state", {"q": {"type": "noul"}})
        assert consent_gate.blocked()
    assert outbound.urls == []  # Claude·Jev 어느 쪽도 나가지 않았다


def test_outside_the_scope_the_main_ai_policy_is_unchanged(client, family, outbound):
    _, _, group = family
    _consent(group["id"], False)
    transport.post_messages({"x": 1})  # 메인 AI 직접 업로드·채팅 등은 관문 밖: 기존대로 나간다
    jev.ask("state", {"q": {"type": "noul"}})
    assert len(outbound.urls) == 2


def test_revoking_consent_mid_processing_stops_the_following_calls(client, family, outbound):
    _, _, group = family
    _consent(group["id"], True)
    with consent_gate.family_chat(group["id"]):
        transport.post_messages({"x": 1})  # 동의가 있을 때는 나간다
        _consent(group["id"], False)  # 처리 도중 철회
        with pytest.raises(consent_gate.ConsentRequired):
            transport.post_messages({"x": 2})
        _consent(
            group["id"], True
        )  # 다시 켜도 이 처리는 끝까지 막힌다(이미 로컬로 대신한 단계가 있을 수 있다)
        with pytest.raises(consent_gate.ConsentRequired):
            transport.post_messages({"x": 3})
    assert len(outbound.urls) == 1


def test_worker_threads_inherit_the_scope(client, family, outbound):
    _, _, group = family
    _consent(group["id"], False)
    with consent_gate.family_chat(group["id"]):
        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(
                ex.map(
                    consent_gate.carry(lambda _i: _try_send()),
                    range(3),
                )
            )
    assert results == ["blocked"] * 3 and outbound.urls == []


def _try_send() -> str:
    try:
        transport.post_messages({"x": 1})
        return "sent"
    except consent_gate.ConsentRequired:
        return "blocked"


def test_a_consent_lookup_failure_blocks(client, family, outbound, monkeypatch):
    _, _, group = family
    _consent(group["id"], True)
    monkeypatch.setattr("app.shared.ai_guard.is_enabled", lambda db, g: 1 / 0)  # 동의를 읽지 못한다
    with consent_gate.family_chat(group["id"]):
        with pytest.raises(consent_gate.ConsentRequired):
            transport.post_messages({"x": 1})
    assert outbound.urls == []


# ---------- 등록 흐름 ----------
def test_a_chat_document_without_consent_is_held_and_sends_nothing(client, family, outbound):
    a, _, group = family
    _consent(group["id"], False)
    msg = _send_file(client, a)
    assert _items(group["id"]) == []  # 등록 보류
    assert outbound.urls == []
    assert msg["attachment"]["id"]  # 채팅 첨부는 그대로 보내졌다


def test_a_chat_document_with_consent_is_registered(client, family, outbound):
    a, _, group = family
    _consent(group["id"], True)
    _send_file(client, a)
    assert len(_items(group["id"])) == 1


def test_consent_revoked_during_masking_registers_nothing_even_with_a_local_fallback(
    client, family, outbound, monkeypatch
):
    """가리기 단계가 Claude 를 부르기 직전에 동의가 꺼진다: 관문이 막고, 가리기가 로컬 규칙으로 대신해도 등록하지 않는다."""
    a, _, group = family
    _consent(group["id"], True)

    def mask_via_claude_with_local_fallback(text, family=None):
        _consent(group["id"], False)  # 처리 도중 철회
        try:
            transport.post_messages({"mask": True})
        except transport.LLMUnavailable:
            pass  # 실제 코드처럼 실패하면 로컬 규칙으로 대신한다(이름·주소가 남을 수 있다)
        kind = masking.sensitive_kind(text)
        return masking.mask_text(text, kind), {}, kind

    monkeypatch.setattr(llm_ingest, "mask", mask_via_claude_with_local_fallback)
    _send_file(client, a)
    assert _items(group["id"]) == []  # 로컬로 대신 가린 문서는 등록되지 않았다
    assert outbound.urls == []  # 막힌 호출은 나가지 않았다


def _photo_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_a_chat_photo_judged_document_without_consent_is_held(
    client, family, outbound, monkeypatch
):
    a, _, group = family
    _consent(group["id"], False)
    monkeypatch.setattr(library, "_judge_photo", lambda gid, data: ("document", None))
    started = []
    monkeypatch.setattr(library.files, "process_file", lambda *a, **k: started.append(1))
    r = client.post(
        "/family-chat/photos", files={"file": ("a.jpg", _photo_bytes(), "image/jpeg")}, headers=a
    )
    assert r.status_code == 201
    att = r.json()["attachment"]["id"]
    library.register_chat_photo(group["id"], "u", att, _photo_bytes())
    assert started == [] and outbound.urls == []
    with SessionLocal() as db:
        # 문서로 판별돼도 등록을 보류하면 document 가 아니라 unsure 로 적는다: document 로 적으면 확인 목록·재검사·일반 사진 확인이
        # 모두 막혀 업로더가 손댈 수 없는 사진이 된다(독립 리뷰 H1). unsure 는 동의를 켠 뒤 재검사로 다시 판별·등록할 수 있다
        assert db.get(ChatPhotoCheck, att).status == "unsure"
    r = client.post(
        f"/family-chat/photos/{att}/check",
        json={"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True},
        headers=a,
    )
    assert r.status_code == 200, r.text  # 업로더가 일반 사진으로 확인할 수 있다


def test_consent_revoked_during_the_last_external_call_registers_nothing(
    client, family, outbound, monkeypatch
):
    """마지막 외부 호출(가리기)이 나간 뒤 철회되고 이어지는 호출이 없어도, 등록 직전에 동의를 다시 확인해 등록하지 않는다(독립 리뷰 M1)."""
    a, _, group = family
    _consent(group["id"], True)
    monkeypatch.setattr(settings, "typesafe_api_key", "")  # 뒤따르는 분류 호출이 없는 서버

    def mask_then_revoke(text, family=None):
        transport.post_messages({"mask": True})  # 동의가 있을 때 나간 호출
        _consent(group["id"], False)  # 응답을 기다리는 사이 철회
        kind = masking.sensitive_kind(text)
        return masking.mask_text(text, kind), {}, kind

    monkeypatch.setattr(llm_ingest, "mask", mask_then_revoke)
    _send_file(client, a)
    assert _items(group["id"]) == []


# ---------- #520 의 행동 시험 이관(PDF·PPT·재검사·처리 중 철회) ----------
def _scanned_pdf(pages: int = 3) -> bytes:
    """글자 층이 없는 여러 쪽 PDF(스캔 문서 대역, 합성)."""
    imgs = [Image.new("RGB", (300, 400), (250 - i * 10, 250, 250)) for i in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def test_scanned_pdf_pages_read_in_worker_threads_are_not_sent_without_consent(
    client, family, outbound
):
    _, _, group = family
    _consent(group["id"], False)
    with consent_gate.family_chat(group["id"]):
        with pytest.raises(
            transport.LLMUnavailable
        ):  # ConsentRequired 는 LLMUnavailable 의 한 종류
            llm_ingest.ocr_pdf(_scanned_pdf())
        assert consent_gate.blocked()
    assert outbound.urls == []  # 쪽마다 스레드에서 읽어도 한 쪽도 나가지 않았다


def test_scanned_pdf_pages_are_sent_with_consent(client, family, outbound):
    _, _, group = family
    _consent(group["id"], True)
    with consent_gate.family_chat(group["id"]):
        text, _note = llm_ingest.ocr_pdf(_scanned_pdf(2))
    assert len(outbound.urls) == 2 and "ok" in text  # 동의가 있으면 쪽마다 Claude 로 읽는다


def test_pptx_pictures_described_in_worker_threads_are_not_sent_without_consent(
    client, family, outbound, monkeypatch
):
    from app.features.ai_assistant.ingest import figures

    _, _, group = family
    _consent(group["id"], False)
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    big = io.BytesIO()
    Image.new("RGB", (400, 300), (120, 160, 200)).save(
        big, format="PNG"
    )  # 설명 대상 최소 크기 이상
    monkeypatch.setattr(
        figures,
        "pptx_pictures",
        lambda data: [[("그림", big.getvalue())], [("그림", big.getvalue())]],
    )
    with consent_gate.family_chat(group["id"]):
        figures.describe_pptx(b"pptx", "슬라이드 글")
        assert consent_gate.blocked()  # 막혔다는 표시가 남아 등록 단계가 결과를 버린다
    assert outbound.urls == []


def test_recheck_without_consent_judges_locally_and_sends_nothing(
    client, family, outbound, monkeypatch
):
    """업로더가 판별 실패 사진을 재검사해도, 동의가 없으면 판별(로컬)만 하고 문서함 등록(외부 읽기)은 보류한다."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.features.family_chat import photo_check_repository as checks

    a, _, group = family
    _consent(group["id"], False)
    monkeypatch.setattr(
        library, "_judge_photo", lambda gid, data: ("failed", "OcrFailed")
    )  # 처음 판별은 실패
    started = []
    monkeypatch.setattr(library.files, "process_file", lambda *a, **k: started.append(1))
    r = client.post(
        "/family-chat/photos", files={"file": ("a.jpg", _photo_bytes(), "image/jpeg")}, headers=a
    )
    att = r.json()["attachment"]["id"]
    with SessionLocal() as db:
        assert db.get(ChatPhotoCheck, att).status == "failed"
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == att)
            .values(
                checked_at=datetime.now(UTC) - timedelta(minutes=10),
                created_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        db.commit()
    assert checks.RECHECK_COOLDOWN < timedelta(minutes=10)
    monkeypatch.setattr(
        library, "_judge_photo", lambda gid, data: ("document", None)
    )  # 재검사 판별은 문서
    started.clear()
    rc = client.post(f"/family-chat/photos/{att}/recheck", headers=a)
    assert rc.status_code in (200, 202), rc.text
    assert started == [] and outbound.urls == []
    with SessionLocal() as db:
        # 문서로 판별됐지만 동의가 없어 등록을 보류했다: 업로더가 손댈 수 있게 unsure 로 남는다(동의를 켠 뒤 재검사하면 등록된다)
        assert db.get(ChatPhotoCheck, att).status == "unsure"


def test_manual_save_to_library_without_consent_is_403_and_changes_nothing(
    client, family, outbound
):
    a, _, group = family
    _consent(group["id"], False)
    r = client.post(
        "/family-chat/photos", files={"file": ("a.jpg", _photo_bytes(), "image/jpeg")}, headers=a
    )
    att = r.json()["attachment"]["id"]
    with SessionLocal() as db:
        before = db.get(ChatPhotoCheck, att).status
    saved = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert saved.status_code == 403 and saved.json()["code"] == "ai_not_enabled"
    with SessionLocal() as db:
        assert db.get(ChatPhotoCheck, att).status == before
    assert outbound.urls == []
