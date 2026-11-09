"""가족 전체방에 올린 사진 중 문서를 찍은 사진은 가족 공유 문서함에 자동 등록된다(일반 사진·애매한 사진·1:1 방·민감 문서는 등록하지 않는다).
판별은 로컬 OCR 의 글자 수·줄 수로 하고, 가족당 하루 상한을 넘으면 자동 등록을 멈춘다. 모델이나 인터넷 없이 돈다."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.ai_assistant.models import Photo
from app.features.family_chat import file_service, photo_service
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import doc_ai
from app.shared.llm.transport import LLMUnavailable
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
PRESCRIPTION_LINES = [
    "서울약국 처방전",
    "환자 김가비 주민등록번호 앞자리",
    "처방의약품 아목시실린 캡슐 250밀리그램",
    "투약일수 3일 용법 1일 3회 식후 복용",
    "조제일자 2026년 11월 5일 조제약사",
    "복약지도 충분한 물과 함께 복용하세요",
    "의료기관 가비내과의원 처방의 확인",
    "약국 보관 처방전 사본 조제 완료",
]


class ScriptedOcr:
    """읽을 때마다 정해 둔 줄을 돌려준다(판별 한 번, 읽기 한 번)."""

    def __init__(self, *texts, conf=0.9):
        self.texts, self.conf, self.calls = texts, conf, 0

    def read(self, image):
        texts = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return [OcrLine(t, self.conf) for t in texts]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    file_service.upload_limiter._failures.clear()
    photo_service.upload_limiter._failures.clear()
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_counts.clear()
    old = files.processors
    yield
    files.processors = old


def _use_ocr(ocr):
    files.processors = files.Processors(ocr=ocr)


def _send_photo(client, headers, room_id=None):
    out = io.BytesIO()
    Image.new("RGB", (320, 240), (235, 235, 235)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _items(group_id):
    with SessionLocal() as db:
        return list(db.scalars(select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)))


def test_a_document_photo_in_the_family_room_is_registered(client, family):
    a, b, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)
    items = _items(group["id"])
    assert [i.source_attachment_id for i in items] == [msg["attachment"]["id"]]
    listed = client.get("/ai-assistant/knowledge/items", headers=b).json()
    assert [row["id"] for row in listed] == [items[0].id]  # 가족 누구나 문서함에서 본다


def test_an_ordinary_photo_is_not_registered_and_leaves_nothing(client, family, tmp_path):
    a, _, group = family
    _use_ocr(ScriptedOcr([]))
    _send_photo(client, a)
    assert _items(group["id"]) == []
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []
    assert not (tmp_path / "raw").exists() or not list((tmp_path / "raw").rglob("*.*"))


def test_an_unsure_photo_is_left_for_the_user(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(["큰 글씨 행사 안내 포스터 입니다 여러분 오세요" * 2] * 3))
    _send_photo(client, a)
    assert _items(group["id"]) == []  # 글자는 있어도 줄이 적다: 자동 등록하지 않는다


def test_document_photos_in_one_to_one_rooms_are_not_registered(client, family):
    a, b, group = family
    me_b = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": me_b}, headers=a).json()
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a, room_id=room["id"])
    assert _items(group["id"]) == []


def test_a_sensitive_document_photo_is_not_registered(client, family, tmp_path):
    a, _, group = family
    _use_ocr(ScriptedOcr(PRESCRIPTION_LINES))
    _send_photo(client, a)
    assert _items(group["id"]) == []
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []


def test_a_photo_that_reads_as_a_picture_after_the_full_read_is_dropped(client, family):
    """판별은 문서였는데 전체 읽기에서 글자가 거의 없으면(사진 기록) 문서함에 넣지 않는다."""
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES, ["간판"]))
    _send_photo(client, a)
    assert _items(group["id"]) == []


def test_the_daily_limit_stops_automatic_registration(client, family, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(library, "PHOTO_DAILY_LIMIT", 1)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    _send_photo(client, a)
    assert len(_items(group["id"])) == 1  # 두 번째는 상한 때문에 건너뛴다


def test_deleting_the_message_removes_the_registered_photo(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)
    assert len(_items(group["id"])) == 1
    r = client.delete(f"/family-chat/messages/{msg['id']}", headers=a)
    assert r.status_code in (200, 204), r.text
    assert _items(group["id"]) == []


# ---------- Claude 판별(혼합): OCR 이 글자를 읽은 사진만 Claude 에게 문서 여부를 묻는다 ----------


@pytest.fixture
def judge(monkeypatch):
    """Claude 판별을 켜고 답을 정해 둔다. 몇 번 불렸는지 센다."""
    monkeypatch.setattr(settings, "photo_judge_llm", True)

    class Judge:
        calls = 0
        answer = doc_ai.PhotoVerdict("document", 0.93, "가정통신문을 정면으로 찍음", 1700, 120)

    def fake(jpeg):
        Judge.calls += 1
        if isinstance(Judge.answer, Exception):
            raise Judge.answer
        return Judge.answer

    monkeypatch.setattr(doc_ai, "classify_photo", fake)
    return Judge


def test_claude_confirms_a_document_photo_and_it_is_registered(client, family, judge):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    assert judge.calls == 1 and len(_items(group["id"])) == 1


def test_claude_rejects_a_street_photo_that_ocr_reads_as_a_document(client, family, judge):
    a, _, group = family
    judge.answer = doc_ai.PhotoVerdict("photo", 0.95, "상가 거리 풍경", 1700, 120)
    _use_ocr(ScriptedOcr(NOTICE_LINES))  # 간판 글자가 많아 OCR 만으로는 문서로 읽힌다
    _send_photo(client, a)
    assert judge.calls == 1 and _items(group["id"]) == []


def test_a_low_confidence_document_answer_is_left_for_the_user(client, family, judge):
    a, _, group = family
    judge.answer = doc_ai.PhotoVerdict("document", 0.5, "정류장 시간표", 1700, 120)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    assert _items(group["id"]) == []


def test_a_photo_ocr_cannot_read_is_never_sent_to_claude(client, family, judge):
    a, _, group = family
    _use_ocr(ScriptedOcr([]))
    _send_photo(client, a)
    assert judge.calls == 0 and _items(group["id"]) == []  # 글자가 없는 사진은 외부로 나가지 않는다


def test_an_unsure_ocr_photo_goes_to_claude_and_can_still_be_a_document(client, family, judge):
    """글자는 있는데 줄이 적은 큰 글씨 안내 포스터는 OCR 만으로는 애매하다: Claude 가 문서라고 하면 등록한다."""
    a, _, group = family
    _use_ocr(ScriptedOcr(["큐드럼 뮤직동호회 회원을 모집합니다 문의 전화 010 3454 3193"] * 3))
    _send_photo(client, a)
    assert judge.calls == 1 and len(_items(group["id"])) == 1


def test_a_claude_failure_leaves_the_photo_unregistered(client, family, judge):
    a, _, group = family
    judge.answer = LLMUnavailable("down")
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)  # 채팅 전송은 그대로 성공한다
    assert msg["attachment"]["id"] and _items(group["id"]) == []


def test_the_claude_judge_is_off_by_default(client, family, monkeypatch):
    a, _, group = family
    assert settings.photo_judge_llm is False

    def boom(jpeg):
        raise AssertionError("기본 설정에서는 외부 AI 를 부르면 안 된다")

    monkeypatch.setattr(doc_ai, "classify_photo", boom)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    assert len(_items(group["id"])) == 1  # 로컬 OCR 판별만으로 등록


def test_the_daily_limit_also_bounds_claude_judging(client, family, judge, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(library, "PHOTO_DAILY_LIMIT", 1)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    _send_photo(client, a)
    assert judge.calls == 1 and len(_items(group["id"])) == 1


# ---------- "문서로 저장": 사용자가 직접 문서함에 넣는다(판별·하루 상한을 건너뛴다) ----------


def _save(client, headers, attachment_id):
    return client.post(f"/family-chat/photos/{attachment_id}/library", headers=headers)


def test_saving_a_plain_photo_by_hand_registers_it_without_any_judge(client, family, judge):
    a, b, group = family
    _use_ocr(ScriptedOcr([]))
    msg = _send_photo(client, a)
    assert _items(group["id"]) == []
    r = _save(client, b, msg["attachment"]["id"])  # 가족 누구나 저장할 수 있다
    assert r.status_code == 200 and r.json() == {"status": "queued"}, r.text
    items = _items(group["id"])
    assert [i.source_attachment_id for i in items] == [msg["attachment"]["id"]]
    assert judge.calls == 0  # 직접 저장은 판별을 건너뛴다
    assert items[0].kind_label == "사진"  # 글자가 거의 없으면 그대로 사진 기록으로 남는다


def test_saving_twice_does_not_register_twice(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)  # 자동으로 이미 등록됨
    r = _save(client, a, msg["attachment"]["id"])
    assert r.status_code == 200 and r.json() == {"status": "already"}
    assert len(_items(group["id"])) == 1


def test_saving_ignores_the_daily_limit(client, family, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(library, "PHOTO_DAILY_LIMIT", 0)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)
    assert _items(group["id"]) == []  # 상한 때문에 자동 등록은 멈췄다
    assert _save(client, a, msg["attachment"]["id"]).status_code == 200
    assert len(_items(group["id"])) == 1


def test_a_photo_in_a_one_to_one_room_cannot_be_saved(client, family):
    a, b, group = family
    me_b = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": me_b}, headers=a).json()
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a, room_id=room["id"])
    r = _save(client, a, msg["attachment"]["id"])
    assert r.status_code == 409 and _items(group["id"]) == []


def test_saving_an_unknown_photo_or_as_an_outsider_is_refused(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a)
    assert _save(client, a, "nosuchphoto1").status_code == 404
    outsider = signup(client, "남")
    # 가족이 없는 사용자는 기존 규칙(current_group_id)대로 거절된다: 사진이 있는지도 알려주지 않는다
    assert _save(client, outsider, msg["attachment"]["id"]).status_code in (400, 403, 404)
