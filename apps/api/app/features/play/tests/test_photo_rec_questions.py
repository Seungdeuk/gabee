import random
from datetime import UTC, date, datetime

from app.features.play.photo_rec_questions import event_question, events_on, month_question
from app.features.schedule.models import Event
from app.shared.db import SessionLocal

G = "g-photo-q"
DAY = date(2026, 3, 5)
TAKEN = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)  # 한국 3월 5일 21시


class LastChoice(random.Random):
    """choice 가 항상 마지막 후보를 고르게 해서 질문 종류를 고정한다."""

    def choice(self, seq):
        return seq[-1]


def add_shared(db, eid, title, day=DAY, place="", group=G, deleted=False):
    """공동 일정 = 원본 + 그것을 가리키는 복사본(origin_id)."""
    base = {"group_id": group, "title": title, "place": place, "start_date": day, "created_by": "u"}
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db.add(Event(id=eid, starts_at=now, **base))
    db.add(
        Event(
            id=f"{eid}c",
            starts_at=now,
            origin_id=eid,
            deleted_at=now if deleted else None,
            **base,
        )
    )
    db.commit()


def test_month_question_shape():
    q = month_question(TAKEN, random.Random(1))
    assert q.kind == 1
    assert q.question == "이 사진은 몇 월에 찍었을까요?"
    assert len(q.options) == 4 and len(set(q.options)) == 4
    assert all(o.endswith("월") and 1 <= int(o[:-1]) <= 12 for o in q.options)
    assert q.options[q.answer_index] == "3월"


def test_month_uses_local_time():
    q = month_question(datetime(2026, 2, 28, 20, 0, tzinfo=UTC), random.Random(1))
    assert q.options[q.answer_index] == "3월"


def test_month_none_when_no_taken_at():
    assert month_question(None, random.Random(1)) is None


def test_event_question_single_event(client):
    with SessionLocal() as db:
        add_shared(db, "e1", "제주 여행")
        add_shared(db, "e2", "할머니 생신", day=date(2026, 4, 1))
        add_shared(db, "e3", "운동회", day=date(2026, 5, 1))
        q = event_question(db, G, TAKEN, random.Random(1))
    assert q.kind == 2
    assert q.question == "이 사진은 어느 일정 때 찍었을까요?"
    assert 3 <= len(q.options) <= 4 and len(set(q.options)) == len(q.options)
    assert q.options[q.answer_index] == "제주 여행"


def test_event_question_needs_two_options(client):
    with SessionLocal() as db:
        add_shared(db, "e1", "제주 여행")
        assert event_question(db, G, TAKEN, random.Random(1)) is None


def test_event_question_place_when_title_unusable(client):
    with SessionLocal() as db:
        add_shared(db, "e1", "아주아주아주아주 긴 일정 제목입니다 정말로", place="제주도")
        add_shared(db, "e2", "점심", day=date(2026, 4, 1), place="부산")
        q = event_question(db, G, TAKEN, random.Random(1))
    assert q.question == "어디서 찍었을까요?"
    assert q.options[q.answer_index] == "제주도"
    assert "부산" in q.options


def test_event_question_place_chosen(client):
    with SessionLocal() as db:
        add_shared(db, "e1", "여행", place="제주도")
        add_shared(db, "e2", "점심", day=date(2026, 4, 1), place="부산")
        q = event_question(db, G, TAKEN, LastChoice(1))
    assert q.question == "어디서 찍었을까요?"
    assert q.options[q.answer_index] == "제주도"


def test_event_skipped_when_ambiguous_or_long(client):
    long_title = "가" * 21
    with SessionLocal() as db:
        add_shared(db, "e0", "다른 날", day=date(2026, 4, 1))
        add_shared(db, "e1", "제주 여행")
        add_shared(db, "e2", "병원 진료")
        assert event_question(db, G, TAKEN, random.Random(1)) is None  # 같은 날 둘
        add_shared(db, "l1", long_title, day=date(2026, 6, 1))
        add_shared(db, "l2", "보기용", day=date(2026, 7, 1))
        assert event_question(db, G, datetime(2026, 6, 1, 3, tzinfo=UTC), random.Random(1)) is None


def test_event_skipped_for_request_born_and_deleted(client):
    with SessionLocal() as db:
        # 부탁에서 생긴 일정: 복사본 없이 원본 형태만 있다
        db.add(
            Event(
                id="r1",
                group_id=G,
                title="부탁 일정",
                start_date=DAY,
                starts_at=datetime(2026, 1, 1, tzinfo=UTC),
                created_by="u",
            )
        )
        add_shared(db, "e2", "다른 날", day=date(2026, 4, 1))
        add_shared(db, "e3", "지운 일정", deleted=True)
        db.commit()
        assert events_on(db, G, DAY) == []
        assert event_question(db, G, TAKEN, random.Random(1)) is None


def test_events_on_scopes_group_and_day(client):
    with SessionLocal() as db:
        add_shared(db, "e1", "내 일정")
        add_shared(db, "e2", "남의 일정", group="other")
        add_shared(db, "e3", "다른 날", day=date(2026, 3, 6))
        assert [e.title for e in events_on(db, G, DAY)] == ["내 일정"]
