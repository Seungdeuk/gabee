"""가족 전체방에 올린 사진 중 문서를 찍은 사진은 가족 공유 문서함에 자동 등록된다(일반 사진·애매한 사진·1:1 방·민감 문서는 등록하지 않는다).
판별은 로컬 OCR 의 글자 수·줄 수로 하고, 가족당 하루 상한을 넘으면 자동 등록을 멈춘다. 모델이나 인터넷 없이 돈다."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest import converters
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.ai_assistant.models import Photo
from app.features.family_chat import file_service, photo_service
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import doc_ai
from app.shared.llm.transport import LLMUnavailable
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
    photo_service.library_limiter._failures.clear()
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    library._photo_counts.clear()
    library._photo_pending.clear()
    library._photo_inflight.clear()
    old = files.processors
    yield
    files.processors = old


def _use_ocr(ocr):
    files.processors = files.Processors(ocr=ocr)


def _send_photo(client, headers, room_id=None, data=None):
    if data is None:
        out = io.BytesIO()
        Image.new("RGB", (320, 240), (235, 235, 235)).save(out, format="JPEG")
        data = out.getvalue()
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", data, "image/jpeg")},
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
def judge(client, family, monkeypatch):
    """Claude 판별을 켜고(가족 AI 동의도 켠다) 답을 정해 둔다. 몇 번 불렸는지 센다."""
    monkeypatch.setattr(settings, "photo_judge_llm", True)
    allow_ai(client, family[0], monkeypatch)

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


# ---------- 리뷰 반영: 운영 기본 OCR, 위치 정보, AI 동의, 중복·상한 ----------


def _jpeg_with_metadata() -> bytes:
    img = Image.new("RGB", (320, 240), (235, 235, 235))
    exif = img.getexif()
    exif[0x010F] = "TestCam"  # 제조사
    exif[0x8825] = {1: "N", 2: (37.0, 33.0, 59.0)}  # GPS
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif, comment=b"secret-comment")
    return out.getvalue()


def test_the_default_ocr_is_used_when_the_server_has_no_ocr_configured(client, family, monkeypatch):
    """운영 서버는 files.processors.ocr 가 None 이다: 판별도 기본 OCR 을 써야 하고, 안 쓰면 늘 애매함이라 자동 등록이 영영 안 된다."""
    a, _, group = family
    files.processors = files.Processors()  # ocr=None
    monkeypatch.setattr(converters, "default_ocr", lambda: ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    assert len(_items(group["id"])) == 1


def test_a_failed_judge_never_sends_the_photo_to_claude(client, family, judge):
    a, _, group = family

    class BrokenOcr:
        def read(self, image):
            raise RuntimeError("model missing")

    _use_ocr(BrokenOcr())
    _send_photo(client, a)
    assert judge.calls == 0 and _items(group["id"]) == []  # 읽지 못한 사진은 외부로 나가지 않는다


def test_the_library_original_has_no_location_or_comment_metadata(client, family):
    a, b, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    msg = _send_photo(client, a, data=_jpeg_with_metadata())
    items = _items(group["id"])
    assert len(items) == 1
    r = client.get(
        f"/ai-assistant/files/{items[0].id}/original", headers=b
    )  # 가족 누구나 내려받는다
    assert r.status_code == 200, r.text
    with Image.open(io.BytesIO(r.content)) as stored:
        exif = stored.getexif()
        assert (
            0x8825 not in exif and 0x010F not in exif
        )  # 촬영 위치·기기 정보가 문서함에 남지 않는다
        assert not stored.info.get("comment")
    assert msg["attachment"]["id"] == items[0].source_attachment_id


def test_without_the_family_ai_consent_claude_never_sees_the_photo(client, family, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(settings, "photo_judge_llm", True)  # 가족 AI 동의는 켜지 않았다

    def boom(jpeg):
        raise AssertionError("AI 동의를 켜지 않은 가족의 사진을 외부 AI 로 보내면 안 된다")

    monkeypatch.setattr(doc_ai, "classify_photo", boom)
    _use_ocr(ScriptedOcr(NOTICE_LINES))
    _send_photo(client, a)
    assert len(_items(group["id"])) == 1  # OCR 이 문서라고 한 사진은 로컬 판별만으로 등록
    _use_ocr(ScriptedOcr(["큐드럼 뮤직동호회 회원을 모집합니다 문의 전화 010 3454 3193"] * 3))
    _send_photo(client, a)
    assert len(_items(group["id"])) == 1  # 애매한 사진은 Claude 없이는 등록하지 않는다


def test_claude_says_document_but_the_full_read_finds_a_picture_so_it_is_dropped(
    client, family, judge
):
    a, _, group = family
    _use_ocr(ScriptedOcr(NOTICE_LINES, ["간판"]))
    _send_photo(client, a)
    assert judge.calls == 1 and _items(group["id"]) == []


def test_saving_a_sensitive_photo_by_hand_registers_nothing(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(PRESCRIPTION_LINES))
    msg = _send_photo(client, a)
    assert _save(client, a, msg["attachment"]["id"]).status_code == 200
    assert _items(group["id"]) == []
    with SessionLocal() as db:
        assert (
            db.scalars(select(Photo)).all() == []
        )  # 민감 문서는 직접 저장해도 문서함에 넣지 않는다


def test_a_second_save_while_the_first_is_still_running_is_ignored(client, family, monkeypatch):
    a, _, group = family
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append((fn, args)))
    _use_ocr(ScriptedOcr([]))
    msg = _send_photo(client, a)  # 자동 판별 작업 1개가 대기한다
    att = msg["attachment"]["id"]
    assert _save(client, a, att).json() == {"status": "queued"}
    assert _save(client, a, att).json() == {
        "status": "queued"
    }  # 진행 중인 같은 요청은 한 번만 처리한다
    assert len(queued) == 2  # 자동 1 + 직접 저장 1
    for fn, args in queued:
        fn(*args)
    assert len(_items(group["id"])) == 1


def test_saving_is_rate_limited_per_user(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(photo_service, "LIBRARY_SAVE_LIMIT", 2)
    _use_ocr(ScriptedOcr([]))
    msg = _send_photo(client, a)
    att = msg["attachment"]["id"]
    assert _save(client, a, att).status_code == 200
    assert _save(client, a, att).status_code == 200
    r = _save(client, a, att)
    assert r.status_code == 429 and r.headers.get("Retry-After")


def test_one_familys_backlog_does_not_block_another_family(monkeypatch):
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append((fn, args)))
    monkeypatch.setattr(library, "PHOTO_QUEUE_LIMIT", 1)
    library._on_photo("g1", "u1", "a1", b"x", False)
    library._on_photo("g1", "u1", "a2", b"x", False)  # 같은 가족의 두 번째는 대기열이 차서 건너뛴다
    library._on_photo("g2", "u2", "a3", b"x", False)  # 다른 가족은 영향이 없다
    assert len(queued) == 2


def test_a_failed_submit_gives_the_queue_slot_back(monkeypatch):
    monkeypatch.setattr(library, "PHOTO_QUEUE_LIMIT", 1)

    def boom(fn, *args):
        raise RuntimeError("executor shut down")

    monkeypatch.setattr(library, "_submit", boom)
    library._on_photo("g1", "u1", "a1", b"x", False)
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append(fn))
    library._on_photo("g1", "u1", "a2", b"x", False)
    assert len(queued) == 1  # 실패한 자리가 영영 차 있지 않다


# ---------- 학교 납부 계좌가 든 안내문은 등록한다(계좌번호만 이유로 민감해진 문서) ----------

FEE_NOTICE_LINES = [
    "해솔초등학교 과회비 납부 안내문",
    "과회비 200,000원 이십만원을 납부해 주세요",
    "기간 2026년 11월 4일부터 11월 8일까지",
    "방법 우리은행 1002-123-456789 예금주 해솔초등학교",
    "계좌이체 시 학생 본인 이름으로 입금해 주세요",
    "과회비 내역 1학기 40,000원 2학기 40,000원",
    "문의 담임선생님 또는 행정실 감사합니다",
    "해솔초등학교장 드림",
]
PASSBOOK_LINES = [
    "국민은행 통장 사본",
    "예금주 김가비 보통예금 통장",
    "계좌번호 123456-12-345678",
    "개설일 2024년 3월 2일 입출금 통장",
    "거래점 서울지점 은행 보관용 사본",
    "예금거래 내역 확인용 통장 첫 장",
    "본인 확인 후 사용하세요 통장 사본",
    "국민은행 서울지점 통장 발급",
]


def test_a_school_fee_notice_with_a_bank_account_is_registered_with_the_number_masked(
    client, family
):
    a, _, group = family
    _use_ocr(ScriptedOcr(FEE_NOTICE_LINES))
    _send_photo(client, a)
    items = _items(group["id"])
    assert (
        len(items) == 1 and items[0].sensitivity == "normal"
    )  # 학교 납부 계좌 안내는 개인 민감 문서가 아니다
    assert (
        "1002" not in items[0].body_md and "456789" not in items[0].body_md
    )  # 계좌번호는 가려서 저장한다


def test_a_passbook_copy_is_still_not_registered(client, family):
    a, _, group = family
    _use_ocr(ScriptedOcr(PASSBOOK_LINES))
    msg = _send_photo(client, a)
    assert _items(group["id"]) == []
    assert _save(client, a, msg["attachment"]["id"]).status_code == 200  # 직접 저장해도 같다
    assert _items(group["id"]) == []
