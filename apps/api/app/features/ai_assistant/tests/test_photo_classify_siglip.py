"""가족방 사진 판별의 SigLIP2 단독 연결(스위치 `PHOTO_CLASSIFY_SIGLIP`, 기본 꺼짐; 로컬 OCR 은 서비스에 없다). 점수기는 가짜(모델 없이 돈다):
점수 계산과 규칙 자체는 ingest/tests/test_siglip_margin.py, 동의 없는 갈래 막기는 ingest/tests/test_external_consent.py, 여기서는
업로드 → 판별 → 상태 표 → 문서함 흐름과 가족 AI 동의를 본다. 외부 AI 호출은 없다(Claude 는 가짜로 막는다). 합성 이미지만 쓴다. 공개 평가 결과와 섞지 않는다."""

import io
import sys

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import converters, llm_ingest, siglip_margin
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.family_chat import file_service, photo_service
from app.features.family_chat.models import ChatPhotoCheck
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import doc_ai
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
MENU_LINES = [
    f"메뉴 {i} 김치찌개 된장찌개 비빔밥 {i}000원 오늘의 추천" for i in range(8)
]  # 글자가 많아도 SigLIP2 가 메뉴판으로 보면 문서가 아니다(로컬 OCR 은 판별에 쓰지 않는다)


class ScriptedOcr:
    """읽기 단계에 끼우는 구성 요소 대역. 판별에는 쓰이지 않는다(호출 횟수로 확인한다)."""

    def __init__(self, *texts, conf=0.9):
        self.texts, self.conf, self.calls = texts, conf, 0

    def read(self, image):
        texts = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return [OcrLine(t, self.conf) for t in texts]


class FakeScorer:
    def __init__(self, margin=0.0, error=None):
        self.margin, self.error, self.calls = margin, error, 0

    def score(self, data):
        self.calls += 1
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
    """문서 사진은 Claude 로만 읽으므로 자동 등록에는 가족 AI 동의가 필요하다: 이 모듈의 가족은 기본으로 동의한 상태다(동의 없는 시험은 끈다)."""
    allow_ai(client, family[0], monkeypatch)
    return family


@pytest.fixture
def staged(monkeypatch):
    """스위치를 켜고 가짜 점수기를 끼운다."""
    monkeypatch.setattr(settings, "photo_classify_siglip", True)
    monkeypatch.setattr(
        settings, "photo_judge_llm", True
    )  # 예전 Claude 판별 스위치: 켜져 있어도 값은 무시된다(사진을 보내지 않는다)

    def use(margin=0.0, error=None):
        scorer = FakeScorer(margin, error)
        siglip_margin.set_scorer(scorer)
        return scorer

    return use


def _use_ocr(ocr):
    files.processors = files.Processors(ocr=ocr)


def _send_photo(client, headers, room_id=None) -> str:
    out = io.BytesIO()
    Image.new("RGB", (320, 240), (235, 235, 235)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
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


def test_a_document_photo_is_registered(client, family, staged):
    a, _, group = family
    scorer = staged(margin=8.0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert scorer.calls == 1
    assert (_check(att).status, _check(att).source) == ("document", "auto")
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]  # 기존 문서함 등록 경로


def test_an_ordinary_photo_is_unsure_never_photo(client, family, staged):
    a, _, group = family
    staged(margin=-6.0)
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    row = _check(att)
    assert (
        row.status == "unsure"
    )  # 자동으로 photo 를 만들지 않는다(D-13): 일반 사진 확인은 업로더가 한다
    assert _items(group["id"]) == []


def test_a_sparse_document_above_the_threshold_is_registered_and_kept(client, family, staged):
    """글자가 거의 없는 문서(읽기 단계가 '사진' 기록으로 보는 사진)도 SigLIP2 가 문서로 봤으면 document 로 등록하고 문서함에 남긴다."""
    a, _, group = family
    staged(margin=7.0)
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    assert _check(att).status == "document"
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]


@pytest.mark.parametrize(
    ("margin", "status"),
    [(5.01, "document"), (5.0, "unsure"), (3.21, "unsure"), (1.0, "unsure")],
)
def test_the_threshold_is_five_and_strictly_greater(client, family, staged, margin, status):
    """초기 기준: margin > 5. 평가에서 놓친 글자 적은 문서(2.14~3.21)는 unsure 로 남아 업로더가 직접 확인한다."""
    a, _, group = family
    staged(margin=margin)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert _check(att).status == status
    assert len(_items(group["id"])) == (1 if status == "document" else 0)


def test_a_menu_board_full_of_text_is_not_a_document_without_ocr_help(client, family, staged):
    a, _, group = family
    staged(margin=-2.4)  # 메뉴판처럼 보인다
    ocr = ScriptedOcr(MENU_LINES)
    _use_ocr(ocr)
    att = _send_photo(client, a)
    assert _check(att).status == "unsure" and _items(group["id"]) == []
    assert ocr.calls == 0  # 판별은 OCR 을 읽지 않는다


def test_the_judge_never_calls_the_ocr(client, family, staged):
    a, _, _ = family
    staged(margin=-6.0)
    ocr = ScriptedOcr(NOTICE_LINES)
    _use_ocr(ocr)
    _send_photo(client, a)
    assert ocr.calls == 0


def test_a_scorer_failure_is_failed_not_a_verdict(client, family, staged):
    a, _, group = family
    staged(error=siglip_margin.MarginError("WorkerExited"))
    _use_ocr(
        ScriptedOcr(NOTICE_LINES)
    )  # 문서처럼 보이는 글이 있어도 점수를 못 구하면 확정하지 않는다
    att = _send_photo(client, a)
    row = _check(att)
    assert (row.status, row.last_error) == ("failed", "SiglipWorkerExited")
    assert _items(group["id"]) == []


def test_an_unexpected_scorer_exception_is_failed(client, family, staged):
    a, _, group = family
    staged(error=RuntimeError("boom"))
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert (_check(att).status, _check(att).last_error) == ("failed", "SiglipRuntimeError")
    assert _items(group["id"]) == []


def test_a_timeout_failure_is_reported_as_timeout(client, family, staged):
    from app.features.family_chat import photo_check_service

    a, _, _ = family
    staged(error=siglip_margin.MarginError("InferTimeout"))
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    row = _check(att)
    assert photo_check_service.failure_kind(row.status, row.last_error) == "timeout"


def test_a_one_to_one_room_photo_is_never_classified(client, family, staged):
    a, b, group = family
    me_b = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": me_b}, headers=a).json()
    scorer = staged(margin=9.0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a, room_id=room["id"])
    assert scorer.calls == 0 and _items(group["id"]) == []


def test_documents_stay_inside_their_own_family(client, family, staged):
    a, _, group = family
    staged(margin=8.0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    outsider = signup(client, "outsider@example.com")
    assert client.get("/ai-assistant/knowledge/items", headers=outsider).status_code in (
        400,
        403,
        404,
    )
    assert _check(att).group_id == group["id"]


def test_the_switch_is_off_by_default_so_every_photo_is_unsure(client, family):
    """스위치가 꺼져 있으면 판별 수단이 없다: 문서처럼 보여도(점수기를 끼워도 부르지 않는다) 모두 unsure 이고 문서 자동 등록은 멈춘다."""
    a, _, group = family
    assert settings.photo_classify_siglip is False
    scorer = FakeScorer(margin=9.0)
    siglip_margin.set_scorer(scorer)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert scorer.calls == 0
    assert _check(att).status == "unsure" and _items(group["id"]) == []


# ---------- 가족 AI 동의: 글자는 Claude 로만 읽으므로, 동의가 없으면 사진을 보내지 않는다 ----------


@pytest.fixture
def claude_reads(monkeypatch):
    """서비스 기본 설정(Claude 로 읽는다)과 Claude 읽기 대역. 몇 번 불렸는지 센다."""
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", False)

    class Reader:
        calls = 0

    def read(image):
        Reader.calls += 1
        return doc_ai.OcrOut("\n".join(NOTICE_LINES), False, 1, 1)

    monkeypatch.setattr(llm_ingest, "ocr_image", read)
    return Reader


def _consent_off(client, headers):
    r = client.put("/family-chat/ai/settings", json={"enabled": False}, headers=headers)
    assert r.status_code == 200, r.text


def test_with_consent_a_document_photo_is_read_by_claude_and_registered(
    client, family, staged, claude_reads
):
    a, _, group = family
    staged(margin=8.0)
    att = _send_photo(client, a)
    assert claude_reads.calls == 1
    assert _check(att).status == "document"
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]


def test_without_consent_a_document_photo_stays_in_the_chat_and_is_never_sent(
    client, family, staged, claude_reads
):
    a, _, group = family
    _consent_off(client, a)
    scorer = staged(margin=8.0)  # 로컬 판별은 문서로 본다
    att = _send_photo(client, a)
    assert scorer.calls == 1  # 판별은 로컬이라 한다
    assert claude_reads.calls == 0  # 사진은 외부로 나가지 않는다
    row = _check(att)
    assert (row.status, row.source) == (
        "unsure",
        "auto",
    )  # document 로 적으면 숨겨지므로 unsure: 사진은 채팅에 남고 업로더가 확인한다
    assert _items(group["id"]) == []  # 자동 등록은 보류


def test_without_consent_saving_by_hand_is_refused_before_anything_is_sent(
    client, family, staged, claude_reads
):
    a, _, group = family
    staged(margin=-6.0)
    att = _send_photo(client, a)
    _consent_off(client, a)
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 403 and r.json()["code"] == "ai_consent_required", r.text
    assert claude_reads.calls == 0 and _items(group["id"]) == []
    assert _check(att).status == "unsure"  # 판별 상태도 바꾸지 않는다(문서로 표시하지 않는다)
    allow_ai_again = client.put("/family-chat/ai/settings", json={"enabled": True}, headers=a)
    assert allow_ai_again.status_code == 200
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 200 and r.json() == {"status": "queued"}
    assert claude_reads.calls == 1 and len(_items(group["id"])) == 1  # 동의하면 저장된다


def test_a_registered_photo_still_answers_already_after_consent_is_turned_off(
    client, family, staged, claude_reads
):
    a, _, group = family
    staged(margin=8.0)
    att = _send_photo(client, a)
    _consent_off(client, a)
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 200 and r.json() == {"status": "already"}


def test_main_ai_direct_image_upload_keeps_claude_reading_even_without_family_consent(
    client, family, claude_reads
):
    """메인 AI 직접 업로드는 기존 정책 유지(사용자 결정 2026-11-23, ADR 0023): 가족 AI 동의와 무관하게 새로 403 으로 막히지 않고 Claude 가 읽는다.
    가족 채팅방 경로(자동 등록·"문서로 저장")의 동의 검사와 다르다 — 그쪽은 위 시험들이 본다."""
    a, _, group = family
    _consent_off(client, a)
    out = io.BytesIO()
    Image.new("RGB", (200, 100), (250, 250, 250)).save(out, format="PNG")
    r = client.post(
        "/ai-assistant/files", files={"file": ("a.png", out.getvalue(), "image/png")}, headers=a
    )
    assert r.status_code == 201, r.text
    assert claude_reads.calls == 1  # 기존대로 Claude 가 읽는다
    assert len(_items(group["id"])) == 1


# ---------- 로컬 OCR 은 서비스에 없다 ----------


def test_the_local_ocr_is_gone_and_the_photo_flow_never_imports_it(
    client, family, staged, monkeypatch
):
    a, _, group = family
    monkeypatch.setitem(
        sys.modules, "rapidocr", None
    )  # import 하면 ImportError: 의존성을 뺀 서버와 같다
    assert not hasattr(converters, "KoreanOcr") and not hasattr(converters, "default_ocr")
    staged(margin=8.0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert _check(att).status == "document" and len(_items(group["id"])) == 1


# ---------- 대기열 상한: 인스턴스 전체 건수·바이트 ----------


def test_the_instance_wide_queue_limits_count_and_bytes(monkeypatch):
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append((fn, args)))
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)
    monkeypatch.setattr(library, "PHOTO_QUEUE_INSTANCE_LIMIT", 3)
    monkeypatch.setattr(library, "PHOTO_QUEUE_INSTANCE_BYTES", 100)
    for i in range(5):  # 가족이 달라도 인스턴스 전체로 3건까지만 받는다
        library._on_photo(f"g{i}", "u", f"a{i}", b"x", False)
    assert len(queued) == 3
    # 건수가 아니라 바이트 상한: 새 인스턴스 상태에서 큰 사진은 한 장만 들어간다
    queued.clear()
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)
    monkeypatch.setattr(library, "PHOTO_QUEUE_INSTANCE_LIMIT", 100)
    library._on_photo("g1", "u", "b1", b"x" * 60, False)
    library._on_photo("g2", "u", "b2", b"x" * 60, False)  # 60 + 60 > 100: 건너뛴다
    assert len(queued) == 1
    # 직접 누른 저장은 상한 때문에 버리지 않는다
    library._on_photo("g3", "u", "b3", b"x" * 60, True)
    assert len(queued) == 2


def test_the_queue_bytes_and_slots_are_given_back_after_a_run(monkeypatch):
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)
    monkeypatch.setattr(library, "register_chat_photo", lambda *a, **k: None)
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._on_photo("g1", "u", "a1", b"x" * 10, False)
    assert library._photo_bytes == 0 and library._photo_pending == {}
