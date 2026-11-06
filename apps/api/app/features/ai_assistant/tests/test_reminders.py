"""먼저 챙겨주기: 문서 날짜에서 챙길 일 뽑기, 앱을 열 때 먼저 하는 말, 채팅 답 반영, 켜고 끄기. 가짜 Claude 로 돈다."""

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.features.ai_assistant import family_names, files, reminders
from app.features.ai_assistant.knowledge import rag_chat, service, tools
from app.features.ai_assistant.models import DocumentReminder
from app.features.schedule.models import Event
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import doc_ai
from tests.helpers import join_family, signup

KST = timezone(timedelta(hours=9))


@pytest.fixture
def clan(client):
    """강민훈(소유자)·강민수가 있는 가족. (헤더, 헤더, 그룹, {이름: user_id})."""
    a = signup(client, "강민훈", "parent")
    group = client.post("/family-group/groups", json={"name": "강씨네"}, headers=a).json()
    b = signup(client, "강민수")
    join_family(client, a, group["invite_code"], b)
    with SessionLocal() as db:
        ids = {m.name: m.user_id for m in family_names.load_members(db, group["id"])}
    return a, b, group, ids


def at(day: str, hour: int = 12, minute: int = 0) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hour, minute, tzinfo=KST)


def _doc(db, group, uid, dates="2026-11-12", extra=""):
    body = f"# 가정통신문\n분류: 학교 가정통신문\n- 날짜: {dates}\n현장체험학습 안내\n{extra}"
    return service.ingest(
        db, group["id"], uid, kind_label="학교 가정통신문", title="가정통신문", body_md=body
    ).id


def _row(db, group, uid, **kw):
    fields = dict(
        id=f"r{db.scalar(select(DocumentReminder.id).limit(1)) is None}{len(kw)}{kw.get('title', 'x')}"[
            :32
        ],
        group_id=group["id"],
        user_id=uid,
        item_id="item1",
        title="독감 예방접종",
        due_date=date(2026, 11, 12),
    )
    fields.update(kw)
    r = DocumentReminder(**fields)
    db.add(r)
    db.commit()
    return r


def _plans(*plans):
    return lambda *a, **k: list(plans)


def P(label, day, urgent=False, lead=0, t=""):
    return doc_ai.ReminderPlan(label, day, t, urgent, lead)


# ---------- 뽑기 ----------
def test_plan_keeps_only_dates_found_in_the_document_and_cleans_labels(clan, monkeypatch):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    monkeypatch.setattr(
        doc_ai,
        "plan_reminders",
        _plans(
            P("[가족:abc] 참가 동의서 제출 [이름]", "2026-11-12", True, 9, "9:30"),
            P("문서에 없는 날짜", "2026-11-20"),  # 문서에서 찾지 않은 날짜는 버린다
            P("", "2026-11-12"),  # 이름이 없으면 버린다
            P("참가 동의서 제출", "2026-11-12", True, 1),  # 정리하면 같은 줄이라 한 번만
        ),
    )
    with SessionLocal() as db:
        item = _doc(db, group, uid, "2026-11-12, 2026-11-01")  # 11-01 은 이미 지난 날짜
        assert reminders.plan(db, group["id"], uid, item, now=at("2026-11-05")) == 1
        row = db.scalars(select(DocumentReminder)).one()
        assert row.title == "참가 동의서 제출" and row.due_date == date(2026, 11, 12)
        assert row.urgent and row.lead_days == 3  # 3일까지만
        assert row.due_time == time(9, 30) and row.status == "proposed" and row.user_id == uid


def test_plan_owner_is_the_tagged_family_member_else_the_uploader(clan, monkeypatch):
    _, _, group, ids = clan
    monkeypatch.setattr(doc_ai, "plan_reminders", _plans(P("접종", "2026-11-12")))
    with SessionLocal() as db:
        tagged = _doc(db, group, ids["강민훈"], extra=f"환자: [가족:{ids['강민수']}]")
        reminders.plan(db, group["id"], ids["강민훈"], tagged, now=at("2026-11-05"))
        assert db.scalars(select(DocumentReminder)).one().user_id == ids["강민수"]


def test_plan_does_nothing_when_the_owner_turned_it_off(clan, monkeypatch):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    monkeypatch.setattr(doc_ai, "plan_reminders", _plans(P("접종", "2026-11-12")))
    with SessionLocal() as db:
        reminders.set_enabled(db, uid, False)
        item = _doc(db, group, uid)
        assert reminders.plan(db, group["id"], uid, item, now=at("2026-11-05")) == 0
        assert db.scalars(select(DocumentReminder)).all() == []


def test_plan_without_dates_skips_the_model_call(clan, monkeypatch):
    _, _, group, ids = clan

    def boom(*a, **k):
        raise AssertionError("날짜가 없으면 Claude 를 부르지 않는다")

    monkeypatch.setattr(doc_ai, "plan_reminders", boom)
    with SessionLocal() as db:
        item = service.ingest(
            db,
            group["id"],
            ids["강민훈"],
            kind_label="메모",
            title="메모",
            body_md="# 메모\n그냥 글",
        ).id
        assert reminders.plan(db, group["id"], ids["강민훈"], item, now=at("2026-11-05")) == 0


def test_file_hook_is_off_by_default_and_never_breaks_the_upload(clan, monkeypatch):
    _, _, group, ids = clan
    calls = []
    monkeypatch.setattr(reminders, "plan", lambda *a, **k: calls.append(a) or 1)
    files._plan_reminders("i", group["id"], ids["강민훈"])
    assert calls == []  # INGEST_REMINDERS 가 꺼져 있다
    monkeypatch.setattr(settings, "ingest_reminders", True)
    files._plan_reminders("i", group["id"], ids["강민훈"])
    assert len(calls) == 1

    def fail(*a, **k):
        raise doc_ai.LLMUnavailable("test")

    monkeypatch.setattr(reminders, "plan", fail)
    files._plan_reminders("i", group["id"], ids["강민훈"])  # 예외가 밖으로 나오지 않는다


# ---------- 앱을 열 때 하는 말 ----------
def test_propose_is_said_once_a_day_up_to_three_times_and_only_when_on(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        _row(db, group, uid)
        first = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05"))
        assert [n["kind"] for n in first] == ["propose"]
        assert "일정에 넣어 드릴까요" in first[0]["text"] and "독감 예방접종" in first[0]["text"]
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05", 18)) == []  # 같은 날
        for day in ("2026-11-06", "2026-11-07"):
            assert len(reminders.due_nudges(db, group["id"], uid, now=at(day))) == 1
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-08")) == []  # 3번까지
    with SessionLocal() as db:
        _row(db, group, uid, title="다른 일")
        reminders.set_enabled(db, uid, False)
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-09")) == []


def test_resolve_schedule_creates_an_event_and_urgent_notices_come_every_24_hours(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(db, group, uid, title="병원 예약", urgent=True, lead_days=2, due_time=time(14, 0))
        reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05"))  # 일정으로 잡을까요
        out = reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05"))
        assert out["status"] == "scheduled"
        event = db.scalar(select(Event).where(Event.user_id == uid))
        assert event.title == "병원 예약" and event.start_time == time(14, 0) and event.kind == 1

        def said(now):
            return [n["text"] for n in reminders.due_nudges(db, group["id"], uid, now=now)]

        assert said(at("2026-11-09", 20)) == []  # 이틀(48시간)보다 더 남음
        first = said(at("2026-11-10", 15))  # 47시간 남음 -> 48시간 칸
        assert len(first) == 1 and "47시간" in first[0] and "병원 예약" in first[0]
        assert said(at("2026-11-10", 16)) == []  # 같은 칸은 다시 말하지 않는다
        assert said(at("2026-11-11", 13)) == []  # 25시간 남음: 아직 24시간 칸이 아님
        second = said(at("2026-11-11", 15))  # 23시간 남음 -> 24시간 칸
        assert len(second) == 1 and "23시간" in second[0]
        assert said(at("2026-11-12", 10)) == []  # 더 이상 칸이 없다


def test_urgent_without_time_counts_from_nine_in_the_morning(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(db, group, uid, urgent=True, lead_days=1)
        reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05"))
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-11", 8)) == []
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-11", 10))  # 23시간 남음
        assert len(got) == 1 and got[0]["kind"] == "urgent"


def test_not_urgent_event_is_asked_the_day_after_only_if_unchecked(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        a = _row(db, group, uid, title="안내문 읽기")
        b = _row(db, group, uid, title="준비물 챙기기", id="second-row")
        for r in (a, b):
            reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05"))
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-11")) == []  # 아직 전
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-12", 20)) == []  # 당일
        # 하나는 사용자가 일정에서 체크해 둔다
        done = db.scalar(select(Event).where(Event.title == "준비물 챙기기"))
        done.checked = True
        db.commit()
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-13", 9))
        assert [n["kind"] for n in got] == ["followup"]
        assert "안내문 읽기" in got[0]["text"] and "하셨나요" in got[0]["text"]
        assert "다시 잡아" not in got[0]["text"]  # 일정으로 다시 잡자는 제안은 하지 않는다
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-14", 9)) == []  # 한 번만
        assert db.get(DocumentReminder, "second-row").status == "done"


# ---------- 답 반영 ----------
def test_resolve_actions(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r1, r2, r3 = (
            _row(db, group, uid, title=t, id=i)
            for t, i in (("접종", "id-1"), ("서류", "id-2"), ("행사", "id-3"))
        )
        now = at("2026-11-13", 9)
        for r in (r1, r2, r3):
            reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05"))
        # 했어요 -> 일정에 체크가 켜진다
        reminders.resolve(db, group["id"], uid, "id-1", "done", now=now)
        assert db.get(DocumentReminder, "id-1").status == "done"
        assert db.scalar(select(Event).where(Event.title == "접종")).checked is True
        # 오늘로 다시 잡기 -> 오늘 할 일이 새로 생기고 이어서 챙긴다
        reminders.resolve(db, group["id"], uid, "id-2", "redo_today", now=now)
        again = db.get(DocumentReminder, "id-2")
        assert again.due_date == date(2026, 11, 13) and again.status == "scheduled"
        today_event = db.get(Event, again.event_id)
        assert today_event.start_date == date(2026, 11, 13) and today_event.kind == 2
        # 그만 알리기
        reminders.resolve(db, group["id"], uid, "id-3", "dismiss", now=now)
        assert db.get(DocumentReminder, "id-3").status == "dismissed"
        # 이미 정리된 건 다시 만들지 않는다
        out = reminders.resolve(db, group["id"], uid, "id-3", "schedule", now=now)
        assert out["status"] == "dismissed"


def test_resolve_rejects_other_users_unknown_ids_and_bad_actions(clan):
    _, _, group, ids = clan
    with SessionLocal() as db:
        r = _row(db, group, ids["강민훈"], id="mine")
        with pytest.raises(ApiError):
            reminders.resolve(db, group["id"], ids["강민수"], r.id, "dismiss")  # 남의 것
        with pytest.raises(ApiError):
            reminders.resolve(db, group["id"], ids["강민훈"], "none", "dismiss")
        with pytest.raises(ValueError):
            reminders.resolve(db, group["id"], ids["강민훈"], r.id, "delete")
        assert db.get(DocumentReminder, "mine").status == "proposed"


# ---------- 채팅 ----------
def test_chat_prompt_lists_recently_asked_items_and_tools_work(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        assert reminders.note_lines(reminders.pending_for_chat(db, group["id"], uid)) == ""
        r = _row(db, group, uid, id="ask-1")
        reminders.due_nudges(db, group["id"], uid)  # 물어봤다
        lines = reminders.note_lines(reminders.pending_for_chat(db, group["id"], uid))
        assert "ask-1" in lines and "독감 예방접종" in lines
        prompt = rag_chat.system_prompt(reminder_lines=lines)
        assert "resolve_reminder" in prompt and "ask-1" in prompt
        assert "ask-1" not in rag_chat.system_prompt()  # 목록이 없으면 안내도 없다
        got = rag_chat._run_tool(
            db,
            group["id"],
            "resolve_reminder",
            {"reminder_id": r.id, "action": "dismiss"},
            user_id=uid,
        )
        assert got["status"] == "dismissed"
        off = rag_chat._run_tool(
            db, group["id"], "set_reminders", {"enabled": "false"}, user_id=uid
        )
        assert off == {"done": True, "enabled": False} and not reminders.is_enabled(db, uid)
        with pytest.raises(ValueError):  # 사용자 없이는 반영하지 않는다
            rag_chat._run_tool(db, group["id"], "set_reminders", {"enabled": True})
    assert {"resolve_reminder", "set_reminders"} <= {t["name"] for t in tools.TOOL_SPECS}


# ---------- API ----------
def test_nudges_and_settings_api(client, clan):
    a, b, group, ids = clan
    with SessionLocal() as db:
        _row(db, group, ids["강민훈"], id="api-1")
    assert client.get("/ai-assistant/reminders/settings", headers=a).json() == {"enabled": True}
    got = client.post("/ai-assistant/reminders/nudges", headers=a).json()["nudges"]
    assert [n["id"] for n in got] == ["api-1"] and got[0]["kind"] == "propose"
    # 같은 날 다시 열어도 같은 말을 또 하지 않는다
    assert client.post("/ai-assistant/reminders/nudges", headers=a).json() == {
        "nudges": [],
        "message": "",
    }
    # 남의 챙길 일은 보이지 않는다
    assert client.post("/ai-assistant/reminders/nudges", headers=b).json() == {
        "nudges": [],
        "message": "",
    }
    r = client.put("/ai-assistant/reminders/settings", json={"enabled": False}, headers=a)
    assert r.status_code == 200 and r.json() == {"enabled": False}
    assert client.get("/ai-assistant/reminders/settings", headers=a).json() == {"enabled": False}
    assert client.post("/ai-assistant/reminders/nudges", headers=a).json() == {
        "nudges": [],
        "message": "",
    }
    assert client.post("/ai-assistant/reminders/nudges").status_code in (401, 403)


def test_default_clock_helpers_use_the_service_timezone():
    assert reminders._local(datetime(2026, 11, 5, 16, 0, tzinfo=UTC)).date() == date(2026, 11, 6)


def test_a_document_date_already_put_in_the_schedule_is_not_asked_again(clan):
    """업로드 직후 카드(채팅 요청)로 이미 일정에 넣었다면 "일정으로 잡을까요?"를 다시 묻지 않고 그 일정을 이어서 챙긴다."""
    from app.features.schedule import service as schedule_service
    from app.features.schedule.schemas import EventCreate

    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(db, group, uid, urgent=True, lead_days=1)
        event = schedule_service.create(
            db,
            group["id"],
            uid,
            EventCreate(title="독감 예방접종 안내", start_date=date(2026, 11, 12), source="chat"),
        )
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05")) == []
        db.refresh(r)
        assert r.status == "scheduled" and r.event_id == event.id
        # 이어서 급한 일로 미리 알려 준다(시각이 없으면 아침 9시 기준)
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-11", 10))
        assert [n["kind"] for n in got] == ["urgent"]


def _put_event(db, group, uid, title, day=date(2026, 11, 12), start=None):
    from app.features.schedule import service as schedule_service
    from app.features.schedule.schemas import EventCreate

    return schedule_service.create(
        db,
        group["id"],
        uid,
        EventCreate(title=title, start_date=day, start_time=start, source="manual"),
    )


def test_scheduled_event_gets_the_documents_place_time_and_key_memo(clan, monkeypatch):
    """문서에 장소·시각이 적혀 있으면 일정에 넣고, 메모에는 핵심 내용만 적는다. 없으면 고정 문구."""
    _, _, group, ids = clan
    uid = ids["강민훈"]
    monkeypatch.setattr(
        doc_ai,
        "plan_reminders",
        _plans(
            doc_ai.ReminderPlan(
                "현장체험학습",
                "2026-11-12",
                "08:40",
                True,
                2,
                place="국립중앙박물관 [주소]",
                memo="도시락과 물을 챙겨 오세요 [가족:abc]",
            ),
            P("독감 예방접종 확인서 제출", "2026-11-12"),
        ),
    )
    with SessionLocal() as db:
        item = _doc(db, group, uid, "2026-11-12")
        assert reminders.plan(db, group["id"], uid, item, now=at("2026-11-05")) == 2
        rows = {r.title: r for r in db.scalars(select(DocumentReminder))}
        trip, flu = rows["현장체험학습"], rows["독감 예방접종 확인서 제출"]
        assert (trip.place, trip.memo) == ("국립중앙박물관", "도시락과 물을 챙겨 오세요")
        reminders.resolve(db, group["id"], uid, trip.id, "schedule", now=at("2026-11-05"))
        reminders.resolve(db, group["id"], uid, flu.id, "schedule", now=at("2026-11-05"))
        got = db.get(Event, db.get(DocumentReminder, trip.id).event_id)
        assert (got.place, got.memo, got.start_time) == (
            "국립중앙박물관",
            "도시락과 물을 챙겨 오세요",
            time(8, 40),
        )
        plain = db.get(Event, db.get(DocumentReminder, flu.id).event_id)
        assert plain.place == "" and plain.memo == "올려 주신 문서에서 가져왔어요"


def test_several_nudges_are_said_as_one_tidy_message_and_one_stays_a_sentence(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        _row(db, group, uid, title="현장체험학습 참가 동의서 제출", due_date=date(2026, 11, 7))
        _row(db, group, uid, title="학부모 상담 주간", due_date=date(2026, 11, 7), id="second-row")
        found = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06"))
        assert [n["kind"] for n in found] == ["propose", "propose"]
        msg = reminders.compose(found)
        assert msg.startswith("확인해 드릴 게 2가지 있어요.")
        assert msg.count("일정에 넣어 드릴까요?") == 1  # 제목은 한 번만
        assert "**현장체험학습 참가 동의서 제출**\n- 일시: 내일(11월 7일)" in msg
        assert "**학부모 상담 주간**\n- 일시: 내일(11월 7일)" in msg
        assert "다 넣어줘" in msg
        assert reminders.compose(found[:1]) == found[0]["text"]  # 하나뿐이면 문장 그대로
        assert reminders.compose([]) == ""


def test_mixed_nudges_put_urgent_first_and_api_returns_the_message(client, clan):
    a, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        late = _row(
            db, group, uid, title="체험학습", due_date=date(2026, 11, 7), urgent=True, lead_days=1
        )
        reminders.resolve(db, group["id"], uid, late.id, "schedule", now=at("2026-11-05"))
        _row(db, group, uid, title="상담 신청", due_date=date(2026, 11, 20), id="second-row")
        found = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06", 12))
        kinds = [n["kind"] for n in found]
        assert kinds == ["urgent", "propose"]
        msg = reminders.compose(found)
        assert msg.index("곧 다가오는") < msg.index("일정에 넣어 드릴까요?")
        assert "- 남은 시간: 약 21시간" in msg
    body = client.post("/ai-assistant/reminders/nudges", headers=a).json()
    assert body["nudges"] == [] and body["message"] == ""  # 이미 말한 것은 다시 주지 않는다


def test_prep_list_is_asked_as_checklist_and_prepared_stops_further_notices(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(
            db,
            group,
            uid,
            title="현장체험학습",
            due_date=date(2026, 11, 7),
            due_time=time(8, 40),
            urgent=True,
            lead_days=2,
            prep="도시락, 물, 편한 운동화",
            memo="학교 앞 출발",
        )
        first = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05", 9))
        assert (
            "‘현장체험학습’을 찾았어요. 준비물은 **도시락, 물, 편한 운동화**예요. 일정에"
            in first[0]["text"]
        )
        reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05", 9))
        event = db.get(Event, db.get(DocumentReminder, r.id).event_id)
        assert (
            event.memo == "학교 앞 출발 준비물: 도시락, 물, 편한 운동화"
        )  # 메모에 없으면 준비물을 덧붙인다
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06", 10))
        assert [n["kind"] for n in got] == ["urgent"]
        assert "준비물은 **도시락, 물, 편한 운동화**예요." in got[0]["text"]
        assert got[0]["text"].endswith("준비물은 다 챙기셨나요?")
        assert got[0]["prep"] == "도시락, 물, 편한 운동화" and got[0]["title"] == "현장체험학습"
        # "다 챙겼어" -> 미리 알림은 그만하고 일정은 체크하지 않는다
        out = reminders.resolve(db, group["id"], uid, r.id, "prepared", now=at("2026-11-06", 10))
        assert out["status"] == "scheduled" and db.get(Event, event.id).checked is False
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-07", 7)) == []
        # 일정이 지난 뒤에는 했는지 한 번 물어본다
        assert [
            n["kind"] for n in reminders.due_nudges(db, group["id"], uid, now=at("2026-11-08", 9))
        ] == ["followup"]


def test_without_a_prep_list_the_notice_keeps_the_general_question(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(db, group, uid, due_date=date(2026, 11, 7), urgent=True, lead_days=1)
        reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-05"))
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06", 12))
        assert got[0]["text"].endswith("준비는 되셨나요?") and "준비물" not in got[0]["text"]


def test_once_answered_or_told_the_same_item_is_not_asked_again_that_day(clan):
    """답을 했거나 이미 말한 일은 그날 다시 묻지 않는다(5분마다 반복하지 않는다). 다음 날에 이어서 챙긴다."""
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        r = _row(
            db, group, uid, title="체험학습", due_date=date(2026, 11, 7), urgent=True, lead_days=2
        )
        # 오늘 "일정에 넣어줘"라고 답했다 -> 24시간 안이어도 오늘은 더 묻지 않는다
        reminders.resolve(db, group["id"], uid, r.id, "schedule", now=at("2026-11-06", 12))
        for minute in (5, 10, 15):
            assert (
                reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06", 12, minute)) == []
            )
        # 다음 날 아침에는 챙긴다. 그리고 한 번 말했으면 그날 안에 반복하지 않는다
        first = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-07", 7))
        assert [n["kind"] for n in first] == ["urgent"]
        for minute in (5, 10, 15):
            assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-07", 7, minute)) == []


def test_composed_message_uses_the_chat_bubble_markdown_and_time_order():
    """채팅 말풍선은 ## 제목·- 목록·**굵게**를 보여 주고 빈 줄은 지운다. 그 서식에 맞춰 한 줄씩 적는다."""
    urgent = [
        {
            "kind": "urgent",
            "text": "x",
            "title": "학부모 상담 주간",
            "when": "내일(11월 7일) 오후 2시",
            "place": "",
            "prep": "알림장",
            "hours": 25,
            "at": "2026-11-07T14:00:00",
        },
        {
            "kind": "urgent",
            "text": "x",
            "title": "현장체험학습",
            "when": "내일(11월 7일) 오전 8시 40분",
            "place": "국립중앙박물관",
            "prep": "도시락, 물",
            "hours": 20,
            "at": "2026-11-07T08:40:00",
        },
    ]
    msg = reminders.compose(urgent)
    assert msg.split("\n") == [
        "확인해 드릴 게 2가지 있어요.",
        "## 곧 다가오는 일정이에요",
        "**현장체험학습**",
        "- 일시: 내일(11월 7일) 오전 8시 40분",
        "- 장소: 국립중앙박물관",
        "- 준비물: **도시락, 물**",
        "- 남은 시간: 약 20시간",
        "**학부모 상담 주간**",
        "- 일시: 내일(11월 7일) 오후 2시",
        "- 준비물: **알림장**",
        "- 남은 시간: 약 25시간",
        "준비물은 다 챙기셨나요?",
    ]
    assert "\n\n" not in msg and "•" not in msg  # 빈 줄·점 목록은 말풍선에서 깨진다


def test_wording_uses_natural_particles_and_clock_words():
    assert reminders._josa("현장체험학습", "을", "를") == "을"
    assert reminders._josa("독감 예방접종 확인서 제출", "을", "를") == "을"
    assert reminders._josa("상담 신청서", "을", "를") == "를"
    assert reminders._josa("체험학습", "이", "가") == "이"
    assert reminders._josa("학부모 상담", "은", "는") == "은"
    assert reminders._josa("소풍", "은", "는") == "은"
    assert reminders._josa("피아노", "은", "는") == "는"
    assert reminders._clock(time(8, 40)) == "오전 8시 40분"
    assert reminders._clock(time(14, 0)) == "오후 2시"
    assert reminders._clock(time(0, 5)) == "오전 12시 5분"
    assert reminders._clock(time(12, 0)) == "오후 12시"
    today = date(2026, 11, 6)
    assert (
        reminders._when_text(date(2026, 11, 7), time(8, 40), today)
        == "내일(11월 7일) 오전 8시 40분"
    )
    assert reminders._when_text(date(2026, 11, 6), None, today) == "오늘(11월 6일)"
    assert reminders._when_text(date(2026, 11, 8), None, today) == "모레(11월 8일)"
    assert reminders._when_text(date(2026, 11, 13), None, today) == "11월 13일(금)"


def test_an_event_that_existed_before_the_document_is_adopted_not_asked_again(clan):
    """문서를 올리기 전부터 같은 날짜에 같은 일이 일정에 있으면 "일정으로 잡을까요?"를 묻지 않고 그 일정을 챙긴다."""
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        event = _put_event(db, group, uid, "독감 예방접종 확인서 내기")
        r = _row(db, group, uid, urgent=True, lead_days=1)  # 일 이름: 독감 예방접종
        assert r.created_at is not None and event.created_at <= r.created_at
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05")) == []
        db.refresh(r)
        assert r.status == "scheduled" and r.event_id == event.id
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-11", 10))
        assert [n["kind"] for n in got] == ["urgent"]


def test_same_day_items_are_matched_to_their_own_events_not_all_to_one(clan):
    """같은 날 항목이 여럿이면 이름이 맞는 일정에만 연결한다. 일정 하나가 그날 모든 항목을 대신하지 않는다."""
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        a = _row(db, group, uid, title="참가 동의서 제출", due_date=date(2026, 11, 7))
        b = _row(db, group, uid, title="현장체험학습", due_date=date(2026, 11, 7), id="second-row")
        c = _row(db, group, uid, title="학부모 상담", due_date=date(2026, 11, 7), id="third-row")
        ev = _put_event(
            db, group, uid, "참가 동의서 내기", day=date(2026, 11, 7)
        )  # 문서를 올린 뒤에 만든 일정
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-06"))
        assert sorted(n["id"] for n in got) == ["second-row", "third-row"]  # 맞는 것만 빠진다
        db.refresh(a)
        assert a.status == "scheduled" and a.event_id == ev.id
        for r in (b, c):
            db.refresh(r)
            assert r.status == "proposed" and r.event_id is None


def test_an_unrelated_event_on_the_same_day_does_not_count_as_scheduled(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        _put_event(db, group, uid, "치과 정기 검진")
        _row(db, group, uid)  # 독감 예방접종
        got = reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05"))
        assert [n["kind"] for n in got] == ["propose"]


def test_an_earlier_event_at_the_same_time_counts_as_the_same_task(clan):
    _, _, group, ids = clan
    uid = ids["강민훈"]
    with SessionLocal() as db:
        event = _put_event(db, group, uid, "소풍", start=time(8, 40))
        r = _row(db, group, uid, title="현장체험학습", due_time=time(8, 40))
        assert reminders.due_nudges(db, group["id"], uid, now=at("2026-11-05")) == []
        db.refresh(r)
        assert r.event_id == event.id
