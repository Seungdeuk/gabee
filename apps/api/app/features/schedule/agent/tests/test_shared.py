"""에이전트가 공동(공유) 일정을 아는지: 가족 채팅에서는 공동 일정만 읽고, LLM 에 보내는 줄과 카드 요약에 공동이 드러난다."""

from datetime import UTC, datetime, timedelta

from app.features.schedule import service
from app.features.schedule.agent import chat, reader
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
    with SessionLocal() as db:
        personal = reader.read(db, group_id, "personal", user_id=a_id).events
        in_family = reader.read(db, group_id, "family", user_id=a_id).events
        receiver = reader.read(db, group_id, "family", user_id=b_id).events
    assert sorted(e.title for e in personal) == ["같이 일정", "혼자 일정"]
    assert [e.title for e in in_family] == ["같이 일정"]  # 나 혼자 일정은 가족 앞에 나오지 않는다
    assert [e.title for e in receiver] == ["같이 일정"]  # 공유받은 복사본도 공동


def test_prompt_line_and_card_brief_mark_shared(client, family):
    group_id, a_id, _ = _make(client, family)
    with SessionLocal() as db:
        events = {e.title: e for e in reader.read(db, group_id, "personal", user_id=a_id).events}
    shared, alone = events["같이 일정"], events["혼자 일정"]
    when = reader.to_local(shared.starts_at)
    assert chat.event_line(shared.id, when, shared.title, None, shared.shared).endswith(" | 공동")
    assert not chat.event_line(alone.id, when, alone.title, None, alone.shared).endswith("공동")
    assert reader.brief(shared)["shared"] is True and reader.brief(alone)["shared"] is False
