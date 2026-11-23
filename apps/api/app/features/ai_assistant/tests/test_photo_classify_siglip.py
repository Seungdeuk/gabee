"""가족방 사진 판별의 OCR + SigLIP2 단계형(E) 연결(스위치 `PHOTO_CLASSIFY_SIGLIP`, 기본 꺼짐). 점수기는 가짜(모델 없이 돈다): 점수 계산과
규칙 자체는 ingest/tests/test_siglip_margin.py, 여기서는 업로드 → 판별 → 상태 표 → 문서함 흐름을 본다. 외부 AI 호출은 없다(Claude 는 가짜로 막는다).
합성 이미지만 쓴다. 공개 평가 결과와 섞지 않는다."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import siglip_margin
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.family_chat import file_service, photo_service
from app.features.family_chat.models import ChatPhotoCheck
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import doc_ai
from tests.helpers import join_family, signup  # noqa: F401  (family 픽스처가 쓴다)

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
]  # OCR 은 문서로 읽는다


class ScriptedOcr:
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
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_pending.clear()
    library._photo_inflight.clear()

    def no_claude(jpeg):
        raise AssertionError("단계형 판별은 외부 AI 로 사진을 보내지 않는다")

    monkeypatch.setattr(doc_ai, "classify_photo", no_claude)
    old = files.processors
    yield
    files.processors = old
    siglip_margin.set_scorer(None)


@pytest.fixture
def staged(monkeypatch):
    """스위치를 켜고 가짜 점수기를 끼운다."""
    monkeypatch.setattr(settings, "photo_classify_siglip", True)
    monkeypatch.setattr(
        settings, "photo_judge_llm", True
    )  # 켜져 있어도 이 경로는 Claude 를 쓰지 않는다

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


def test_a_sparse_document_that_ocr_misses_is_rescued_and_kept(client, family, staged):
    """OCR 은 글자를 못 읽었지만(0줄) SigLIP2 가 문서로 본 사진: document 로 등록하고, 읽기 단계가 '글자 적음'으로 버리지 않는다."""
    a, _, group = family
    staged(margin=7.0)
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    assert _check(att).status == "document"
    assert [i.source_attachment_id for i in _items(group["id"])] == [att]


def test_a_sparse_document_below_the_rescue_threshold_is_left_for_the_user(client, family, staged):
    a, _, group = family
    staged(margin=5.0)  # 경계: 5 초과여야 한다
    _use_ocr(ScriptedOcr(["간단한 안내문 한 줄"]))
    att = _send_photo(client, a)
    assert _check(att).status == "unsure" and _items(group["id"]) == []


def test_a_menu_board_that_ocr_reads_as_a_document_is_vetoed(client, family, staged):
    a, _, group = family
    staged(margin=-2.4)  # 메뉴판처럼 보인다
    _use_ocr(ScriptedOcr(MENU_LINES))
    att = _send_photo(client, a)
    assert _check(att).status == "unsure" and _items(group["id"]) == []


def test_a_signboard_that_ocr_reads_as_a_document_is_vetoed_at_the_boundary(client, family, staged):
    a, _, group = family
    staged(margin=1.0)  # 경계: 1 초과여야 한다
    _use_ocr(ScriptedOcr(MENU_LINES))
    att = _send_photo(client, a)
    assert _check(att).status == "unsure" and _items(group["id"]) == []


def test_a_scorer_failure_is_failed_not_a_verdict(client, family, staged):
    a, _, group = family
    staged(error=siglip_margin.MarginError("WorkerExited"))
    _use_ocr(ScriptedOcr(NOTICE_LINES))  # OCR 이 문서여도 점수를 못 구하면 확정하지 않는다
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


def test_an_ocr_failure_never_reaches_the_model(client, family, staged):
    a, _, _ = family

    class BrokenOcr:
        def read(self, image):
            raise RuntimeError("ocr down")

    scorer = staged(margin=9.0)
    _use_ocr(BrokenOcr())
    att = _send_photo(client, a)
    assert (_check(att).status, _check(att).last_error) == ("failed", "OcrFailed")
    assert scorer.calls == 0


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


def test_the_switch_is_off_by_default_and_then_the_old_ocr_rule_decides(
    client, family, monkeypatch
):
    a, _, group = family
    assert settings.photo_classify_siglip is False
    scorer = FakeScorer(margin=-9.0)  # 켜졌다면 문서를 막았을 점수
    siglip_margin.set_scorer(scorer)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    att = _send_photo(client, a)
    assert scorer.calls == 0
    assert (
        _check(att).status == "document" and len(_items(group["id"])) == 1
    )  # 기존 OCR 판별 그대로


def test_the_switch_off_keeps_ocr_only_unsure_for_unreadable_photos(client, family):
    a, _, group = family
    scorer = FakeScorer(margin=9.0)
    siglip_margin.set_scorer(scorer)
    _use_ocr(ScriptedOcr([]))
    att = _send_photo(client, a)
    assert scorer.calls == 0 and _check(att).status == "unsure" and _items(group["id"]) == []
