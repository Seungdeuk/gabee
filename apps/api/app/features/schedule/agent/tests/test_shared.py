"""에이전트가 공동(공유) 일정을 아는지: 가족 채팅에서는 공동 일정만 읽고, LLM 에 보내는 줄과 카드 요약에 공동이 드러난다."""

from datetime import UTC, datetime, timedelta

from app.features.schedule import service
from app.features.schedule.agent import chat, handler, prompts, reader
from app.features.schedule.schemas import EventCreate
from app.shared.db import SessionLocal


def _ids(client, a, b):
    return (
        client.get("/family-group/me", headers=a).json()["id"],
        client.get("/family-group/me", headers=b).json()["id"],
    )


def _make(client, family):
    a, b, group = family
    a_id, b_id = _ids(client, a, b)
    soon = datetime.now(UTC) + timedelta(days=1)
    with SessionLocal() as db:
        service.create(db, group["id"], a_id, EventCreate(title="혼자 일정", starts_at=soon))
        service.create(
            db,
            group["id"],
            a_id,
            EventCreate(title="같이 일정", starts_at=soon, share_with=[b_id]),
        )
    return group["id"], a_id, b_id


def test_family_channel_reads_only_shared_events(client, family):
    group_id, a_id, b_id = _make(client, family)
    room = {
        a_id,
        b_id,
    }  # 가족방 구성원(2026-11-25: 가족방은 구성원 모두가 볼 수 있는 일정만 읽는다)
    with SessionLocal() as db:
        personal = reader.read(db, group_id, "personal", user_id=a_id).events
        in_family = reader.read(db, group_id, "family", user_id=a_id, room_member_ids=room).events
        receiver = reader.read(db, group_id, "family", user_id=b_id, room_member_ids=room).events
        unknown_room = reader.read(db, group_id, "family", user_id=a_id).events
    assert sorted(e.title for e in personal) == ["같이 일정", "혼자 일정"]
    assert [e.title for e in in_family] == ["같이 일정"]  # 나 혼자 일정은 가족 앞에 나오지 않는다
    assert [e.title for e in receiver] == ["같이 일정"]  # 공유받은 복사본도 공동
    assert (
        unknown_room == []
    )  # 방 구성원을 모르면 가족방에서는 아무 일정도 읽지 않는다(fail-closed)


def test_prompt_line_and_card_brief_mark_shared(client, family):
    group_id, a_id, _ = _make(client, family)
    with SessionLocal() as db:
        events = {e.title: e for e in reader.read(db, group_id, "personal", user_id=a_id).events}
    shared, alone = events["같이 일정"], events["혼자 일정"]
    when = reader.to_local(shared.starts_at)
    assert chat.event_line(shared.id, when, shared.title, None, shared.shared).endswith(" | 공동")
    assert not chat.event_line(alone.id, when, alone.title, None, alone.shared).endswith("공동")
    assert reader.brief(shared)["shared"] is True and reader.brief(alone)["shared"] is False


class _Ev:
    def __init__(self, title, shared):
        self.title = title
        self.shared = shared


def test_mark_shared_adds_mark_after_shared_titles_only():
    events = [_Ev("치과 예약", True), _Ev("장보기", False)]
    out = chat.mark_shared("내일 치과 예약이 있고, 장보기도 있어요.", events)
    assert out == "내일 치과 예약(공)이 있고, 장보기도 있어요."


def test_mark_shared_keeps_existing_mark_and_handles_repeats():
    events = [_Ev("가족 식사", True)]
    assert chat.mark_shared("가족 식사(공)가 있어요", events) == "가족 식사(공)가 있어요"
    assert (
        chat.mark_shared("가족 식사, 그리고 가족 식사", events)
        == "가족 식사(공), 그리고 가족 식사(공)"
    )


def test_mark_shared_skips_ambiguous_title_and_empty_events():
    mixed = [
        _Ev("병원", True),
        _Ev("병원", False),
    ]  # 같은 제목이 공동·비공동으로 섞이면 구분할 수 없다
    assert chat.mark_shared("병원 가는 날이에요", mixed) == "병원 가는 날이에요"
    assert chat.mark_shared("일정이 없어요", []) == "일정이 없어요"


def test_mark_shared_longer_title_wins_over_contained_title():
    events = [_Ev("가족 식사 준비", True), _Ev("가족 식사", True)]
    assert (
        chat.mark_shared("가족 식사 준비와 가족 식사", events)
        == "가족 식사 준비(공)와 가족 식사(공)"
    )


def test_mark_titles_marks_together_requests_and_shared_events():
    tagged = [("치과 예약", "(공)"), ("장보기", "(함)"), ("헬스장", "")]
    out = chat.mark_titles("치과 예약, 장보기, 헬스장이 있어요.", tagged)
    assert out == "치과 예약(공), 장보기(함), 헬스장이 있어요."
    assert (
        chat.mark_titles("장보기(함) 있어요", tagged) == "장보기(함) 있어요"
    )  # 이미 붙은 곳은 그대로


def test_mark_titles_skips_title_with_different_marks():
    tagged = [("병원", "(공)"), ("병원", "(함)")]  # 같은 제목이 공동·함께로 섞이면 구분할 수 없다
    assert chat.mark_titles("병원 가는 날", tagged) == "병원 가는 날"


def test_system_prompt_and_notices_do_not_ask_model_for_marks():
    # (공)·(함)은 DB 값 기준으로 코드가 붙인다. 모델에게 따로 시키지 않는다.
    assert "(공)" not in prompts.CHAT_SYSTEM and "(공)" not in handler.FAMILY_NOTICE
