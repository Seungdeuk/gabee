"""자동 판별 결과가 사진 판별 상태 표에 어떻게 적히는가(T05-b0-1, D-13): SigLIP2 margin > 5 → document, 그 밖(일반·애매) → unsure
(**어떤 자동 판정도 photo 가 되지 않는다**), 실패 → failed, 못 적거나 대기열이 가득 차면 pending 그대로(타임라인에 안 나온다)."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import siglip_margin
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.family_chat import file_service, photo_service
from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat.models import ChatPhotoCheck
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import consent_gate
from tests.helpers import allow_ai, join_family, signup  # noqa: F401  (family 픽스처가 쓴다)

NOTICE_LINES = [
    "해솔초등학교 가정통신문",
    "2026년 11월 현장체험학습 안내",
    "일시 11월 7일 오전 8시 40분",
    "장소 국립중앙박물관 견학",
    "준비물 도시락 물 모자 편한 신발",
    "참가 여부를 11월 3일까지 알려 주세요",
    "문의 담임선생님 또는 행정실",
    "감사합니다 해솔초등학교장",
]


class ScriptedOcr:
    def __init__(self, *texts, conf=0.9):
        self.texts, self.conf, self.calls = texts, conf, 0

    def read(self, image):
        texts = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return [OcrLine(t, self.conf) for t in texts]


_REAL_CONSENT = (
    consent_gate.family_ai_allowed
)  # 폴더 conftest 가 '동의 켜짐'으로 바꿔 두므로 진짜 확인을 붙잡아 둔다


@pytest.fixture(autouse=True)
def _real_consent_check(monkeypatch):
    monkeypatch.setattr(
        consent_gate, "family_ai_allowed", _REAL_CONSENT
    )  # 이 파일은 실제 가족 AI 동의(allow_ai·끄기)로 시험한다


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    file_service.upload_limiter._failures.clear()
    photo_service.upload_limiter._failures.clear()
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)
    monkeypatch.setattr(
        settings, "photo_classify_siglip", True
    )  # 판별은 SigLIP2 단독이다(로컬 OCR 없음)

    def no_claude(jpeg):
        raise AssertionError("사진 판별에 외부 AI 로 사진을 보내면 안 된다")

    old = files.processors
    yield
    files.processors = old
    siglip_margin.set_scorer(None)


class _FixedMargin:
    """판별을 맡은 SigLIP2 점수기 대역: 늘 같은 margin 을 돌려준다."""

    def __init__(self, margin):
        self.margin = margin

    def score(self, data):
        return self.margin


def _margin_for(ocr) -> float:
    """OCR 대역의 첫 줄 묶음으로 이 시험이 뜻한 판별을 정한다: 6줄 이상이면 문서(8.0), 글자가 있어도 적으면 애매(2.0), 없으면 일반 사진(-4.0).
    판별은 이제 OCR 이 아니라 SigLIP2 라서, 이 묶음은 margin 을 정하는 데만 쓰이고 읽기 단계는 둘째 묶음(없으면 같은 묶음)부터 읽는다."""
    first = ocr.texts[0] if getattr(ocr, "texts", None) else []
    if len(first) >= 6:
        return 8.0
    return 2.0 if first else -4.0


def _use_ocr(ocr, margin=None):
    siglip_margin.set_scorer(_FixedMargin(_margin_for(ocr) if margin is None else margin))
    if getattr(ocr, "texts", None) and len(ocr.texts) > 1:
        ocr.calls = 1
    files.processors = files.Processors(ocr=ocr)


@pytest.fixture
def family(client, family, monkeypatch):
    """문서 사진은 Claude 로만 읽으므로(로컬 OCR 없음) 자동 등록·직접 저장에는 가족 AI 동의가 필요하다: 이 모듈의 가족은 동의한 상태로 둔다."""
    allow_ai(client, family[0], monkeypatch)
    return family


def _send_photo(client, headers) -> str:
    out = io.BytesIO()
    Image.new("RGB", (320, 240), (235, 235, 235)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"]


def _check(attachment_id: str) -> ChatPhotoCheck:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, attachment_id)


def _items(group_id):
    with SessionLocal() as db:
        return list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)))


def test_a_document_photo_is_recorded_as_document_by_auto(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    row = _check(att)
    assert (row.status, row.source) == ("document", "auto") and len(_items(group["id"])) == 1


def test_a_photo_with_no_text_is_unsure_never_photo(client, family):
    """D-13: 글자가 안 읽히는 사진도 자동으로 일반 사진 확정이 되지 않는다(업로더 확인 필요)."""
    a, _, group = family
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    row = _check(att)
    assert (row.status, row.source) == ("unsure", "auto") and _items(group["id"]) == []
    with SessionLocal() as db:
        assert checks.confirmed_photo_ids(db, group["id"], [att]) == set()  # 타임라인 제외


def test_an_unsure_ocr_photo_is_unsure(client, family):
    a, _, _ = family
    _use_ocr(ScriptedOcr(["큰 글씨 행사 안내 포스터 입니다 여러분 오세요" * 2] * 3))
    assert _check(_send_photo(client, a)).status == "unsure"


def test_a_scorer_failure_is_failed_with_the_error_kind_only(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))

    class Broken:
        def score(self, data):
            raise siglip_margin.MarginError("LoadFail")

    siglip_margin.set_scorer(Broken())  # 모델을 못 올렸다: 문서·일반으로 확정하지 않는다
    row = _check(_send_photo(client, a))
    assert (row.status, row.last_error) == ("failed", "SiglipLoadFail")  # 종류 이름만 저장한다
    assert _items(group["id"]) == []


def test_if_recording_fails_the_row_stays_pending_and_the_photo_stays_hidden(
    client, family, monkeypatch
):
    a, _, group = family

    def boom(db, group_id, attachment_id, status, error=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(checks, "record_auto", boom)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)  # 전송은 성공한다
    assert _check(att).status == "pending"
    with SessionLocal() as db:
        assert checks.confirmed_photo_ids(db, group["id"], [att]) == set()


def test_a_full_queue_leaves_the_row_pending(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(library, "PHOTO_QUEUE_LIMIT", 0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    assert (
        _check(_send_photo(client, a)).status == "pending"
    )  # 버려진 사진도 줄이 남아 나중에 이어받는다(b0-3)


def test_a_late_result_does_not_overwrite_a_manual_document(client, family):
    """문서로 저장(수동)한 뒤에 자동 판별 결과가 늦게 와도 상태는 그대로다."""
    a, _, group = family
    monkeypatch_ocr = ScriptedOcr([])
    _use_ocr(monkeypatch_ocr)
    # 판별이 돌기 전에 사람이 문서로 저장한 상황을 만든다: 통로를 잠시 비워 판별을 막고, 수동 저장 뒤 자동 결과를 직접 넣는다
    old = chat_library._on_photo
    chat_library._on_photo = None
    try:
        att = _send_photo(client, a)
    finally:
        chat_library._on_photo = old
    with SessionLocal() as db:
        checks.mark_document_manual(db, group["id"], att)
    chat_library.photo_judged(group["id"], att, "unsure")  # 늦게 도착
    row = _check(att)
    assert (row.status, row.source) == ("document", "manual")


def test_a_late_document_verdict_after_the_uploader_confirmed_does_not_register_the_photo(
    client, family
):
    """b0-2a 리뷰: 업로더가 일반 사진으로 확인(photo/manual)한 뒤 늦게 문서 판정이 와도 상태는 그대로이고, 문서함에 등록하지도 않는다
    (등록하면 타임라인과 문서함 양쪽에 있게 된다)."""
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))  # 판별하면 문서다
    old = chat_library._on_photo
    chat_library._on_photo = None  # 업로드 직후 자동 판별이 돌지 않게 하고(대기열이 밀린 상황)
    try:
        att = _send_photo(client, a)
    finally:
        chat_library._on_photo = old
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = "photo", "manual"  # 업로더 확인(b0-2a)
        db.commit()
    library.register_chat_photo(group["id"], family_user_id(client, a), att, _jpeg_bytes(), False)
    row = _check(att)
    assert (row.status, row.source) == ("photo", "manual")
    assert _items(group["id"]) == []


def family_user_id(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _jpeg_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (320, 240), (235, 235, 235)).save(out, format="JPEG")
    return out.getvalue()


def test_the_one_to_one_room_photo_is_not_judged_into_the_table(client, family):
    a, b, group = family
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    out = io.BytesIO()
    Image.new("RGB", (80, 60), (1, 2, 3)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room["id"]},
        headers=a,
    )
    assert r.status_code == 201
    with SessionLocal() as db:
        assert db.scalars(select(ChatPhotoCheck)).all() == []
