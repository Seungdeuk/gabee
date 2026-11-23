"""처리 목적별 외부 AI 전송 정책 시험(ADR 0023, 사용자 결정 2026-11-23).

- **메인 AI 직접 업로드**(`/ai-assistant/files`): 기존 정책 유지 — 가족 AI 동의와 무관하게 Claude 가 읽고·가리고·분류한다(`Purpose.MAIN_AI_DIRECT_UPLOAD`).
- **가족 소통 채팅방**(문서·사진 자동 등록, "문서로 저장", 재검사): **가족 AI 동의가 있을 때만** 외부(Claude·Jev)로 보낸다(`Purpose.FAMILY_CHAT_DOCUMENT`).
처리 목적은 서버 코드가 정하며 요청 값으로 바꿀 수 없다. Claude·Jev 로 가는 모든 함수를 호출 횟수를 세는 대역으로 바꿔 실제 업로드 경로로 확인한다(실제 API 호출 없음).
각 시험은 짝이 되는 대조군을 둬서 호출이 0 인 것이 그 단계에 닿지 않아서가 아님을 보인다. 합성 데이터만 쓴다.

마지막의 `test_*_is_not_reprotected_*` 는 **아직 고치지 않은 한계**를 기록하는 xfail(strict)이다."""

import ast
import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import doc_classifier, llm_ingest, siglip_margin
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.family_chat import file_service, photo_service
from app.features.family_chat.models import ChatPhotoCheck
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import doc_ai, jev
from tests.helpers import allow_ai, join_family, signup  # noqa: F401  (family 픽스처가 쓴다)

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# 규칙·분류기로 종류가 정해지지 않는 글(분류가 Jev 까지 가야 한다) — 한글 낱말 규칙에 걸리지 않게 영문으로 쓴다
PLAIN_TEXT = "Please bring the green notebook and the blue pencil case tomorrow morning thank you"


def pdf(pages) -> bytes:
    """글자 층이 있는 최소 PDF(영문만). 빈 문자열이면 글자 없는 쪽(스캔 쪽 대역)."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def pptx_with_picture() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "가족 여행 계획"
    pic = io.BytesIO()
    Image.new("RGB", (300, 300), (10, 120, 200)).save(pic, "PNG")
    pic.seek(0)
    slide.shapes.add_picture(pic, Inches(1), Inches(2), width=Inches(3))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def png(color=(240, 240, 240)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(out, "PNG")
    return out.getvalue()


class FakeScorer:
    def __init__(self, margin=0.0, error=None):
        self.margin, self.error = margin, error

    def score(self, data):
        if self.error is not None:
            raise self.error
        return self.margin


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    file_service.upload_limiter._failures.clear()
    photo_service.upload_limiter._failures.clear()
    photo_service.library_limiter._failures.clear()
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)

    def no_claude(jpeg):
        raise AssertionError("사진 판별은 외부 AI 로 사진을 보내지 않는다")

    monkeypatch.setattr(doc_ai, "classify_photo", no_claude)
    old = files.processors
    yield
    files.processors = old
    siglip_margin.set_scorer(None)


@pytest.fixture
def family(client, family, monkeypatch):
    """이 모듈의 가족은 기본으로 동의한 상태다(동의 없는 시험은 `_consent(..., False)` 로 끈다)."""
    allow_ai(client, family[0], monkeypatch)
    return family


class Claude:
    """Claude·Jev 로 가는 모든 함수의 대역: 호출 횟수를 세고, `after_read` 가 있으면 읽기가 끝난 직후 부른다(처리 도중 철회를 흉내 낸다)."""

    def __init__(self):
        self.calls = {
            "ocr_image": 0,
            "ocr_pdf": 0,
            "mask": 0,
            "figure": 0,
            "jev": 0,
            "reminders": 0,
        }
        self.after_read = None

    def total(self) -> int:
        return sum(self.calls.values())

    def reset(self):
        for k in self.calls:
            self.calls[k] = 0

    def _read_done(self):
        if self.after_read is not None:
            self.after_read()


@pytest.fixture
def claude(monkeypatch):
    """서비스 기본 설정(Claude 로 읽고·가리고·분류하고·챙길 일을 뽑는다)을 켜고, 외부로 가는 함수를 세는 대역으로 바꾼다."""
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    monkeypatch.setattr(settings, "ingest_reminders", True)
    monkeypatch.setattr(settings, "photo_classify_siglip", True)
    monkeypatch.setattr(
        doc_classifier, "predict", lambda text: None
    )  # 분류기가 못 정해 Jev 까지 가게 한다
    c = Claude()

    def ocr_image(image):
        c.calls["ocr_image"] += 1
        c._read_done()
        return doc_ai.OcrOut(PLAIN_TEXT, False, 0, 0)

    def ocr_pdf(data):
        c.calls["ocr_pdf"] += 1
        c._read_done()
        return PLAIN_TEXT, None

    def mask(text, family=None):
        c.calls["mask"] += 1
        return text, {}, "none"

    def figure(jpeg):
        c.calls["figure"] += 1
        return doc_ai.OcrOut("파란 사각형 그림", False, 0, 0)

    def jev_ask(state, questions):
        c.calls["jev"] += 1
        return {}  # 키가 없는 답 → 분류는 사람 확인으로 끝난다(호출은 셌다)

    def plan(db, group_id, user_id, photo_id):
        c.calls["reminders"] += 1

    monkeypatch.setattr(llm_ingest, "ocr_image", ocr_image)
    monkeypatch.setattr(llm_ingest, "ocr_pdf", ocr_pdf)
    monkeypatch.setattr(llm_ingest, "mask", mask)
    monkeypatch.setattr(doc_ai, "describe_figure", figure)
    monkeypatch.setattr(jev, "ask", jev_ask)
    monkeypatch.setattr(jev, "available", lambda: True)
    monkeypatch.setattr(files.reminders, "plan", plan)
    return c


@pytest.fixture
def purposes(monkeypatch):
    """`files.process_file` 에 실제로 넘어간 처리 목적을 기록한다(원래 함수도 그대로 부른다)."""
    seen = []
    real = files.process_file

    def spy(*args, **kwargs):
        seen.append(kwargs.get("purpose"))
        return real(*args, **kwargs)

    monkeypatch.setattr(files, "process_file", spy)
    return seen


def _consent(client, headers, enabled: bool):
    r = client.put("/family-chat/ai/settings", json={"enabled": enabled}, headers=headers)
    assert r.status_code == 200, r.text


def _main_upload(client, headers, name, content, ctype, **extra):
    """메인 AI 직접 업로드."""
    r = client.post(
        "/ai-assistant/files", files={"file": (name, content, ctype)}, headers=headers, **extra
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _status(client, headers, file_id) -> str:
    return client.get(f"/ai-assistant/files/{file_id}", headers=headers).json()["status"]


def _chat_file(client, headers, name, content, ctype, **extra):
    """가족 채팅방 문서 첨부(전체방): 서버가 뒤에서 문서함에 자동 등록을 시도한다."""
    r = client.post(
        "/family-chat/files", files={"file": (name, content, ctype)}, headers=headers, **extra
    )
    assert r.status_code == 201, r.text
    return r.json()


def _send_photo(client, headers, color=(235, 235, 235), **extra) -> str:
    out = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
        **extra,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"]


def _items(group_id):
    with SessionLocal() as db:
        return list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)))


def _check(attachment_id: str) -> ChatPhotoCheck:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, attachment_id)


# ======================= 메인 AI 직접 업로드: 기존 정책 유지 =======================


@pytest.mark.parametrize("family_consents", [True, False])
def test_main_ai_photo_upload_is_read_masked_and_classified_by_claude_regardless_of_family_consent(
    client, family, claude, purposes, family_consents
):
    a, _, group = family
    _consent(client, a, family_consents)
    fid = _main_upload(client, a, "p.png", png(), "image/png")  # 새로 403 으로 막히지 않는다
    assert _status(client, a, fid) in ("analyzed", "needs_review")
    assert claude.calls["ocr_image"] == 1  # Claude 읽기
    assert claude.calls["mask"] >= 1 and claude.calls["jev"] >= 1  # 가리기·분류(Jev)도 기존대로
    assert claude.calls["reminders"] >= 1  # 챙길 일 뽑기도 기존대로
    assert len(_items(group["id"])) == 1
    assert purposes == [files.Purpose.MAIN_AI_DIRECT_UPLOAD]


@pytest.mark.parametrize("family_consents", [True, False])
def test_main_ai_pdf_upload_is_read_by_claude_regardless_of_family_consent(
    client, family, claude, family_consents
):
    a, _, group = family
    _consent(client, a, family_consents)
    fid = _main_upload(
        client,
        a,
        "n.pdf",
        pdf(["Hello family notice about the school trip next week", ""]),
        "application/pdf",
    )
    assert _status(client, a, fid) in ("analyzed", "needs_review")
    assert claude.calls["ocr_pdf"] == 1 and claude.calls["mask"] >= 1
    assert len(_items(group["id"])) == 1


@pytest.mark.parametrize("family_consents", [True, False])
def test_main_ai_ordinary_documents_keep_their_existing_processing(
    client, family, claude, family_consents
):
    a, _, group = family
    _consent(client, a, family_consents)
    txt = _main_upload(client, a, "a.txt", PLAIN_TEXT.encode(), "text/plain")
    slides = _main_upload(client, a, "t.pptx", pptx_with_picture(), PPTX)
    assert [_status(client, a, i) in ("analyzed", "needs_review") for i in (txt, slides)] == [
        True,
        True,
    ]
    assert claude.calls["mask"] >= 2  # 글 가리기(Claude)
    assert claude.calls["jev"] >= 1  # 분류(Jev)
    assert claude.calls["figure"] >= 1  # PPT 그림 설명
    assert len(_items(group["id"])) == 2


# ======================= 가족 소통 채팅방: 동의가 있을 때만 외부로 =======================


def test_family_chat_documents_without_consent_send_nothing(client, family, claude, purposes):
    a, _, group = family
    _consent(client, a, False)
    _chat_file(
        client,
        a,
        "n.pdf",
        pdf(["Hello family notice about the school trip next week", ""]),
        "application/pdf",
    )
    _chat_file(client, a, "t.pptx", pptx_with_picture(), PPTX)
    _chat_file(client, a, "a.txt", PLAIN_TEXT.encode(), "text/plain")
    assert len(_items(group["id"])) == 3  # 받아서 로컬로 처리·등록한다
    assert claude.total() == 0, (
        claude.calls
    )  # 읽기·가리기·그림 설명·분류·챙길 일 어느 것도 나가지 않는다
    assert purposes == [files.Purpose.FAMILY_CHAT_DOCUMENT] * 3


def test_family_chat_documents_with_consent_do_reach_claude(client, family, claude):
    """대조군: 위 시험이 0 인 이유가 그 단계에 닿지 않아서가 아님을 보인다."""
    a, _, group = family
    _chat_file(
        client,
        a,
        "n.pdf",
        pdf(["Hello family notice about the school trip next week"]),
        "application/pdf",
    )
    _chat_file(client, a, "t.pptx", pptx_with_picture(), PPTX)
    assert (
        claude.calls["ocr_pdf"] >= 1 and claude.calls["figure"] >= 1 and claude.calls["mask"] >= 2
    )
    assert len(_items(group["id"])) == 2


# ---------- 재검사 ----------


def test_rechecking_without_consent_judges_locally_and_sends_nothing(client, family, claude):
    a, _, group = family
    siglip_margin.set_scorer(FakeScorer(error=siglip_margin.MarginError("LoadFail")))
    att = _send_photo(client, a)
    assert _check(att).status == "failed"
    _consent(client, a, False)
    siglip_margin.set_scorer(FakeScorer(margin=8.0))  # 이제 문서로 판정되지만
    r = client.post(f"/family-chat/photos/{att}/recheck", headers=a)
    assert r.status_code == 200 and r.json()["queued"] is True, r.text
    assert (
        _check(att).status == "unsure"
    )  # 동의가 없어 자동 등록은 보류(document 로 적으면 숨겨진다)
    assert claude.total() == 0 and _items(group["id"]) == []


def test_a_photo_held_for_consent_is_not_rechecked_automatically_but_can_be_saved_by_hand(
    client, family, claude
):
    """알려진 한계: 동의 때문에 보류된 사진은 `unsure` 라서 재검사 대상이 아니다(실패·지연만 재검사). 동의를 켠 뒤에는 수동 "문서로 저장"으로 넣는다."""
    a, _, group = family
    _consent(client, a, False)
    siglip_margin.set_scorer(FakeScorer(margin=8.0))
    att = _send_photo(client, a)
    assert _check(att).status == "unsure" and claude.total() == 0
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)  # 동의 없는 직접 저장은 막힌다
    assert r.status_code == 403 and r.json()["code"] == "ai_consent_required"
    assert claude.total() == 0 and _items(group["id"]) == []
    _consent(client, a, True)
    r = client.post(f"/family-chat/photos/{att}/recheck", headers=a)
    assert (
        r.status_code == 409 and r.json()["code"] == "recheck_not_needed"
    )  # 자동으로 다시 판별되지 않는다
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 200 and r.json() == {"status": "queued"}
    assert claude.calls["ocr_image"] == 1
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]


# ---------- 직접 저장 경합 ----------


def test_forced_registration_is_a_no_op_if_consent_is_revoked_after_the_request_was_accepted(
    client, family, claude
):
    a, _, group = family
    siglip_margin.set_scorer(FakeScorer(margin=-4.0))
    att = _send_photo(client, a)
    uid = client.get("/family-group/me", headers=a).json()["id"]
    _consent(client, a, False)  # 요청은 받아들여졌지만 처리 직전에 철회
    library.register_chat_photo(group["id"], uid, att, b"x", forced=True)
    assert claude.total() == 0 and _items(group["id"]) == []


# ---------- 처리 도중 철회 ----------


def _revoker(client, headers, group_id):
    uid = client.get("/family-group/me", headers=headers).json()["id"]

    def revoke():
        with SessionLocal() as db:
            ai_guard.set_enabled(db, group_id, uid, False)

    return revoke


def test_consent_revoked_while_a_chat_photo_is_being_read_blocks_the_remaining_external_steps(
    client, family, claude
):
    a, _, group = family
    siglip_margin.set_scorer(FakeScorer(margin=8.0))
    _send_photo(client, a, (200, 200, 200))  # 대조군: 철회 없으면 가리기·Jev·챙길 일까지 간다
    assert (
        claude.calls["mask"] >= 1 and claude.calls["jev"] >= 1 and claude.calls["reminders"] >= 1
    ), claude.calls
    claude.reset()
    claude.after_read = _revoker(
        client, a, group["id"]
    )  # 읽기(이미 나간 호출)가 끝나는 순간 철회한다
    att = _send_photo(client, a, (100, 100, 100))
    assert claude.calls == {
        "ocr_image": 1,
        "ocr_pdf": 0,
        "mask": 0,
        "figure": 0,
        "jev": 0,
        "reminders": 0,
    }, claude.calls
    assert att in [
        i.source_attachment_id for i in _items(group["id"])
    ]  # 로컬 규칙으로 가려 저장한다(실패시키지 않는다)


def test_consent_revoked_while_a_chat_pdf_is_being_read_blocks_the_remaining_external_steps(
    client, family, claude
):
    a, _, group = family
    claude.after_read = _revoker(client, a, group["id"])
    _chat_file(
        client,
        a,
        "r.pdf",
        pdf(["Hello family notice about the school trip next week"]),
        "application/pdf",
    )
    assert claude.calls == {
        "ocr_image": 0,
        "ocr_pdf": 1,
        "mask": 0,
        "figure": 0,
        "jev": 0,
        "reminders": 0,
    }, claude.calls
    assert len(_items(group["id"])) == 1


# ---------- 주입된 Jev ----------


def test_an_injected_jev_is_not_called_for_family_chat_without_consent_but_is_with_consent(
    client, family, claude
):
    a, _, _ = family
    calls = []

    def injected(state, questions):
        calls.append(1)
        return {}

    files.processors = files.Processors(jev=injected)
    _consent(client, a, False)
    _chat_file(client, a, "a.txt", PLAIN_TEXT.encode(), "text/plain")
    assert calls == [] and claude.total() == 0  # 끼워 준 Jev 도 동의 없이는 부르지 않는다
    _consent(client, a, True)
    _chat_file(client, a, "b.txt", (PLAIN_TEXT + " again").encode(), "text/plain")
    assert calls  # 대조군: 동의가 있으면 부른다


# ======================= 처리 목적 변조·오용 =======================


def test_each_entry_point_passes_its_own_server_decided_purpose(client, family, claude, purposes):
    a, _, _ = family
    siglip_margin.set_scorer(FakeScorer(margin=8.0))
    _main_upload(client, a, "a.txt", PLAIN_TEXT.encode(), "text/plain")
    _chat_file(client, a, "b.txt", (PLAIN_TEXT + " chat").encode(), "text/plain")
    att = _send_photo(client, a, (50, 60, 70))  # 자동 등록
    siglip_margin.set_scorer(FakeScorer(margin=-4.0))
    plain = _send_photo(client, a, (70, 60, 50))  # 일반 사진 → 직접 저장
    assert client.post(f"/family-chat/photos/{plain}/library", headers=a).status_code == 200
    assert purposes == [
        files.Purpose.MAIN_AI_DIRECT_UPLOAD,
        files.Purpose.FAMILY_CHAT_DOCUMENT,
        files.Purpose.FAMILY_CHAT_DOCUMENT,
        files.Purpose.FAMILY_CHAT_DOCUMENT,
    ], purposes
    assert att


def test_client_supplied_fields_cannot_change_the_purpose_or_skip_the_consent_check(
    client, family, claude, purposes
):
    """요청 본문·쿼리·헤더로 `purpose`·`external` 을 보내도 서버는 쓰지 않는다: 가족 채팅 경로는 동의가 없으면 외부로 보내지 않는다."""
    a, _, group = family
    _consent(client, a, False)
    forged = {"purpose": "main_ai_direct_upload", "external": "true", "recheck": "false"}
    headers = {**a, "X-Process-Purpose": "main_ai_direct_upload", "X-External": "true"}
    r = client.post(
        "/family-chat/files",
        files={"file": ("a.txt", PLAIN_TEXT.encode(), "text/plain")},
        data=forged,
        params=forged,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    siglip_margin.set_scorer(FakeScorer(margin=8.0))
    out = io.BytesIO()
    Image.new("RGB", (320, 240), (90, 90, 90)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data=forged,
        params=forged,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert claude.total() == 0, claude.calls  # 외부 전송 0회
    assert purposes == [
        files.Purpose.FAMILY_CHAT_DOCUMENT
    ]  # 문서는 가족 채팅 목적으로 처리됐다(사진은 보류라 처리 안 함)
    assert len(_items(group["id"])) == 1  # 글 파일만 로컬로 등록, 동의 없는 사진은 보류


def test_a_forged_purpose_on_the_main_ai_route_is_ignored_too(client, family, claude, purposes):
    a, _, _ = family
    _consent(client, a, False)
    _main_upload(
        client,
        a,
        "a.txt",
        PLAIN_TEXT.encode(),
        "text/plain",
        data={"purpose": "family_chat_document"},
        params={"purpose": "family_chat_document"},
    )
    assert purposes == [files.Purpose.MAIN_AI_DIRECT_UPLOAD]  # 서버가 정한 목적 그대로
    assert claude.calls["mask"] >= 1  # 메인 AI 정책(기존 유지)대로 처리된다


def test_process_file_refuses_a_missing_unknown_or_mismatched_purpose(client, family):
    a, _, group = family
    gid = group["id"]
    uid = client.get("/family-group/me", headers=a).json()["id"]
    with pytest.raises(TypeError):  # 목적을 빠뜨리면 조용히 정해지지 않는다
        files.process_file("p", gid, uid, b"x", "a.txt")
    with pytest.raises(ValueError):  # 모르는 목적
        files.process_file("p", gid, uid, b"x", "a.txt", purpose="bogus")
    with pytest.raises(
        ValueError
    ):  # 채팅 첨부가 있는데 메인 AI 목적(채팅 문서를 메인 정책으로 처리하는 오용)
        files.process_file(
            "p",
            gid,
            uid,
            b"x",
            "a.txt",
            source_attachment_id="att",
            purpose=files.Purpose.MAIN_AI_DIRECT_UPLOAD,
        )
    with pytest.raises(ValueError):  # 채팅 목적인데 채팅 첨부가 없다
        files.process_file("p", gid, uid, b"x", "a.txt", purpose=files.Purpose.FAMILY_CHAT_DOCUMENT)


def test_the_main_ai_purpose_is_only_used_by_the_main_ai_upload_route():
    """가족 채팅 쪽 코드가 메인 AI 목적(동의 검사 없음)을 쓰면 안 된다: 운영 코드에서 `MAIN_AI_DIRECT_UPLOAD` 를 쓰는 파일은 정의(`files.py`)와 메인 AI 라우터뿐이다.
    또한 모든 `process_file` 호출은 `purpose=` 를 넘긴다."""
    app = Path(__file__).resolve().parents[3]
    users, missing, inspected = set(), [], 0
    for path in app.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "MAIN_AI_DIRECT_UPLOAD" in text:
            users.add(path.relative_to(app).as_posix())
        if "process_file" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            direct = name == "process_file"
            via_task = name == "add_task" and any(
                isinstance(arg, ast.Attribute) and arg.attr == "process_file" for arg in node.args
            )
            if direct or via_task:
                inspected += 1
                if not any(k.arg == "purpose" for k in node.keywords):
                    missing.append(f"{path.name}:{node.lineno}")
    assert users == {
        "features/ai_assistant/files.py",
        "features/ai_assistant/router.py",
    }, users
    assert inspected >= 3, inspected  # 라우터 1 + 라이브러리 2 (공허한 통과 방지)
    assert missing == [], missing


# ======================= 조회 때 재보호 (알려진 한계) =======================

LOCAL_DOC = "가족 모임 안내\n일시 12월 3일 오후 6시\n장소 서울특별시 강남구 테헤란로 152\n연락처 이영희 010-9999-8888\n참석 여부를 알려 주세요"


def _stored_without_consent(client, a, group, claude) -> KnowledgeItem:
    """동의 없는 가족이 채팅방에 올린 문서: 로컬 규칙으로만 가려 저장된다."""
    _consent(client, a, False)
    _chat_file(client, a, "모임.txt", LOCAL_DOC.encode(), "text/plain")
    assert claude.total() == 0  # 동의가 없어 외부로 나가지 않았다
    items = _items(group["id"])
    assert len(items) == 1
    return items[0]


def test_a_chat_document_stored_without_consent_keeps_names_and_addresses_after_local_masking(
    client, family, claude
):
    """현황 기록: 로컬 규칙은 번호(전화·주민 등)만 가리고 일반 문서의 이름·주소는 남긴다(Claude 가리기는 개인 집 주소·이름도 가렸다, ADR 0014)."""
    a, _, group = family
    item = _stored_without_consent(client, a, group, claude)
    body = client.get(f"/ai-assistant/knowledge/items/{item.id}", headers=a).json()["body_md"]
    assert "010-9999-8888" not in body  # 번호는 가려진다
    assert "테헤란로 152" in body and "이영희" in body  # 이름·주소는 남는다


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="[미해결·정책 결정 필요] 동의 없이 로컬 가리기만 거친 채팅 문서는, 나중에 동의를 켜고 AI 비서가 조회하면 이름·주소가 그대로 Claude 로 간다. "
    "메인 채팅은 조회한 문서를 다시 가리지 않는다(ADR 0014: 보호를 저장 때 Claude 가리기에 맡김). 고쳐지면 이 표시를 지울 것.",
)
def test_a_chat_document_stored_without_consent_is_not_reprotected_before_the_assistant_sends_it(
    client, family, claude, monkeypatch
):
    from app.features.ai_assistant.knowledge import rag_chat

    a, _, group = family
    _stored_without_consent(client, a, group, claude)
    _consent(client, a, True)
    seen = []

    def fake_post(body):
        if not seen:
            seen.append(1)
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t",
                        "name": "search_knowledge",
                        "input": {"query": "가족 모임 장소"},
                    }
                ]
            }
        seen.append(str(body["messages"][-1]["content"][0]["content"]))
        return {"content": [{"type": "text", "text": "확인했어요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "가족 모임 장소가 어디야?"}, headers=a)
    assert r.status_code == 200 and len(seen) >= 2, r.text
    assert (
        "테헤란로 152" not in seen[1] and "이영희" not in seen[1]
    )  # 바라는 보호: 외부로 나가기 전에 다시 가려져야 한다
