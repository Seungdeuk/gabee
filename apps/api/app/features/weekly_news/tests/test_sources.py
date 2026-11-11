"""주간 뉴스 재료 수집(`shared/weekly_sources`)과 주인 기능 쪽 제공자(일정·문서함) 시험.

일정·문서함은 실제 API 로 만들고(공유·복사본 규칙을 그대로 쓰려고), 경계·옛 줄·소프트 삭제는 DB 값을 직접 바꿔 만든다.
수집기 자체의 규칙(미등록·준비 안 됨·예외·상한)은 가짜 제공자와 가짜 상태로 본다.
"""

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select, update

from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.schedule.models import Event
from app.features.weekly_news import evidence
from app.shared import weekly_sources
from app.shared.db import SessionLocal
from app.shared.weekly_sources import SourceRecord
from tests.helpers import join_family, signup

START, END = date(2026, 11, 2), date(2026, 11, 8)  # 월~일
ITEMS = "/ai-assistant/knowledge/items"
SECRET = "비밀본문-메모-장소-XYZ"


# ---------- 도우미 ----------


def _uid(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _event(client, headers, title, day="2026-11-04", kind=1, share_with=(), **extra):
    body = {"title": title, "start_date": day, "kind": kind, "share_with": list(share_with)}
    r = client.post("/schedule/events", json={**body, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _check(client, headers, event_id) -> None:
    r = client.put(f"/schedule/events/{event_id}/checked", json={"checked": True}, headers=headers)
    assert r.status_code == 200, r.text


def _rows(title) -> list[Event]:
    with SessionLocal() as db:
        return list(
            db.scalars(select(Event).where(Event.title == title).order_by(Event.created_at))
        )


def _row_of(title, user_id) -> str:
    return next(e.id for e in _rows(title) if e.user_id == user_id)


def _edit(event_id, **values) -> None:
    with SessionLocal() as db:
        db.execute(update(Event).where(Event.id == event_id).values(**values))
        db.commit()


def _collect(group_id, user_id, start=START, end=END):
    with SessionLocal() as db:
        return weekly_sources.collect(db, group_id, user_id, start, end)


def _titles(collected, kind=None) -> list[str]:
    return [r.title for r in collected.records if kind is None or r.kind == kind]


def _doc(client, headers, title, created_at, label="메모", body=SECRET, **extra) -> str:
    r = client.post(
        ITEMS, json={"kind_label": label, "title": title, "body_md": body, **extra}, headers=headers
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]
    with SessionLocal() as db:
        db.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == item_id)
            .values(created_at=datetime.fromisoformat(created_at).astimezone(UTC))
        )
        db.commit()
    return item_id


# ---------- 일정: 공유 약속 ----------


def test_shared_event_is_included_for_sender_and_receiver(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "가족 저녁", share_with=[ub], start_time="18:30")
    got_a, got_b = _collect(group["id"], ua), _collect(group["id"], ub)
    assert _titles(got_a) == ["가족 저녁"] and _titles(got_b) == ["가족 저녁"]
    # 사람마다 자기 줄을 가리킨다(보낸 사람은 원본, 받은 사람은 복사본)
    assert got_a.records[0].ref == _row_of("가족 저녁", ua)
    assert got_b.records[0].ref == _row_of("가족 저녁", ub)
    assert got_a.records[0].ref != got_b.records[0].ref
    rec = got_a.records[0]
    assert (rec.kind, rec.day, rec.start_time) == ("event", date(2026, 11, 4), "18:30")
    assert got_a.unavailable == [] and got_a.truncated is False


def test_personal_event_is_excluded(client, family):
    a, b, group = family
    _event(client, a, "혼자 치과")
    assert _collect(group["id"], _uid(client, a)).records == []
    assert _collect(group["id"], _uid(client, b)).records == []


def test_event_without_time_has_none_start_time(client, family):
    a, b, group = family
    _event(client, a, "종일 나들이", share_with=[_uid(client, b)])
    assert _collect(group["id"], _uid(client, a)).records[0].start_time is None


def test_pending_event_is_included(client, family):
    a, b, group = family
    _event(client, a, "미정 모임", share_with=[_uid(client, b)], status="pending")
    assert _titles(_collect(group["id"], _uid(client, a))) == ["미정 모임"]


def test_only_my_line_not_the_other_members(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "같이 산책", share_with=[ub])
    _event(client, b, "수진 혼자", day="2026-11-05")
    assert _titles(_collect(group["id"], ua)) == [
        "같이 산책"
    ]  # 수진의 줄·복사본은 지민 재료가 아니다
    assert _titles(_collect(group["id"], ub)) == ["같이 산책"]
    assert len(_collect(group["id"], ua).records) == 1


# ---------- 일정: 공유 할 일 ----------


def test_todo_needs_shared_and_checked(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    done = _event(client, a, "장보기 완료", kind=2, share_with=[ub])
    _event(client, a, "장보기 미완료", kind=2, share_with=[ub])
    solo = _event(client, a, "혼자 할 일", kind=2)
    _check(client, a, done["id"])
    _check(client, a, solo["id"])
    got = _collect(group["id"], ua)
    assert _titles(got) == ["장보기 완료"] and got.records[0].kind == "todo"
    # 받은 사람은 자기 복사본을 직접 체크해야 자기 재료에 들어간다(원본의 체크는 번지지 않는다)
    assert _collect(group["id"], ub).records == []
    _check(client, b, _row_of("장보기 미완료", ub))
    assert _titles(_collect(group["id"], ub)) == ["장보기 미완료"]


def test_checked_appointment_and_unchecked_appointment_both_count(client, family):
    a, b, group = family
    ev = _event(client, a, "체크한 약속", share_with=[_uid(client, b)])
    _check(client, a, ev["id"])  # 약속(kind=1)은 체크 여부와 상관없다
    _event(client, a, "체크 안 한 약속", share_with=[_uid(client, b)])
    got = _collect(group["id"], _uid(client, a))
    assert sorted(_titles(got, "event")) == ["체크 안 한 약속", "체크한 약속"]


# ---------- 일정: 주 경계·삭제·옛 줄 ----------


def test_week_boundaries_by_start_date(client, family):
    a, b, group = family
    ub = _uid(client, b)
    for title, day in [
        ("전 일요일", "2026-11-01"),
        ("월요일", "2026-11-02"),
        ("일요일", "2026-11-08"),
        ("다음 월요일", "2026-11-09"),
    ]:
        _event(client, a, title, day=day, share_with=[ub])
    assert _titles(_collect(group["id"], _uid(client, a))) == ["월요일", "일요일"]


def test_soft_deleted_event_is_excluded(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "취소된 약속", share_with=[ub])
    _edit(_row_of("취소된 약속", ua), deleted_at=datetime.now(UTC))
    assert _collect(group["id"], ua).records == []
    assert _titles(_collect(group["id"], ub)) == [
        "취소된 약속"
    ]  # 받은 사람의 복사본은 그대로 그 사람의 일정


def test_sender_original_stays_shared_when_the_receiver_deleted_the_copy(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "복사본 삭제", share_with=[ub])
    _edit(_row_of("복사본 삭제", ub), deleted_at=datetime.now(UTC))
    # 공유 관계는 지워도 남는다(`with_sharing` 계산 그대로)
    assert _titles(_collect(group["id"], ua)) == ["복사본 삭제"]
    assert _collect(group["id"], ub).records == []


def test_legacy_rows_without_start_date_use_starts_at_in_kst(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    cases = {
        "옛 전 일요일 끝": "2026-11-01T14:59:59+00:00",  # KST 11/1 23:59:59
        "옛 월요일 0시": "2026-11-01T15:00:00+00:00",  # KST 11/2 00:00:00
        "옛 일요일 끝": "2026-11-08T14:59:59+00:00",  # KST 11/8 23:59:59
        "옛 다음 월요일 0시": "2026-11-08T15:00:00+00:00",  # KST 11/9 00:00:00
    }
    for title, starts_at in cases.items():
        _event(client, a, title, share_with=[ub])
        _edit(_row_of(title, ua), start_date=None, starts_at=datetime.fromisoformat(starts_at))
    got = _collect(group["id"], ua)
    assert sorted(_titles(got)) == ["옛 월요일 0시", "옛 일요일 끝"]
    assert {r.title: r.day for r in got.records} == {
        "옛 월요일 0시": date(2026, 11, 2),
        "옛 일요일 끝": date(2026, 11, 8),
    }


def test_row_with_start_date_ignores_a_conflicting_starts_at(client, family):
    a, b, group = family
    ua = _uid(client, a)
    _event(client, a, "날짜 우선", day="2026-11-04", share_with=[_uid(client, b)])
    _edit(_row_of("날짜 우선", ua), starts_at=datetime(2026, 12, 25, tzinfo=UTC))
    assert _collect(group["id"], ua).records[0].day == date(2026, 11, 4)


def test_ownerless_legacy_rows_count_only_when_shared(client, family):
    """주인이 없던 옛 줄(그룹 전체가 본다)도 "공유" 계산을 그대로 거친다: 복사본이 있는 줄만 들어가고, 복사본이 없는 옛 줄은 빠진다."""
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "옛 공용 줄", share_with=[ub])
    _event(client, a, "옛 개인 줄")
    shared_original = _row_of("옛 공용 줄", ua)
    _edit(shared_original, user_id=None)
    _edit(_row_of("옛 개인 줄", ua), user_id=None)
    copy = _row_of("옛 공용 줄", ub)
    # 지민에게는 복사본이 있는 주인 없는 원본만 공유다. 수진에게는 자기 복사본만 들어간다: 주인 없는 원본은 수진 쪽에서 보면
    # 공유 상대(주인)가 없어 `with_sharing` 이 공유로 보지 않는다(옛 줄의 한계). 공유 안 한 옛 줄은 둘 다 아니다
    assert [r.ref for r in _collect(group["id"], ua).records] == [shared_original]
    assert [r.ref for r in _collect(group["id"], ub).records] == [copy]


def test_accepted_request_event_counts_as_shared(client, family):
    """부탁(같이해요)을 수락해서 생긴 일정(`request_id`)은 `with_sharing` 이 공유로 본다. 할 일로 받으면 체크해야 들어간다."""
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    for title, kind in [("부탁 약속", 1), ("부탁 할 일", 2)]:
        r = client.post(
            "/schedule/requests",
            json={"title": title, "start_date": "2026-11-05", "to_ids": [ub]},
            headers=a,
        )
        assert r.status_code == 201, r.text
        answered = client.post(
            f"/schedule/requests/{r.json()['id']}/answer",
            json={"answer": "accepted", "kind": kind},
            headers=b,
        )
        assert answered.status_code == 200, answered.text
    got = _collect(group["id"], ub)
    assert _titles(got) == ["부탁 약속"]  # 할 일은 아직 체크 전
    assert got.records[0].ref == _row_of("부탁 약속", ub)
    _check(client, b, _row_of("부탁 할 일", ub))
    assert sorted(_titles(_collect(group["id"], ub))) == ["부탁 약속", "부탁 할 일"]
    assert _collect(group["id"], ua).records == []  # 부탁을 보낸 사람에게는 일정 줄이 없다


# ---------- 일정: 가족 경계 ----------


def test_other_family_is_never_mixed(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    c = signup(client, "철수")
    other = client.post("/family-group/groups", json={"name": "옆집"}, headers=c).json()
    d = signup(client, "영희")
    join_family(client, c, other["invite_code"], d)
    uc, ud = _uid(client, c), _uid(client, d)
    _event(client, c, "옆집 잔치", share_with=[ud])
    _event(client, a, "우리 잔치", share_with=[ub])
    assert _titles(_collect(group["id"], ua)) == ["우리 잔치"]
    assert _titles(_collect(other["id"], uc)) == ["옆집 잔치"]
    # 호출자가 잘못된 (그룹, 사람) 쌍을 넘겨도 다른 가족의 줄은 읽히지 않는다
    assert _collect(group["id"], uc).records == []
    assert _collect(other["id"], ua).records == []


# ---------- 일정·문서: 메모·장소·본문은 나오지 않는다 ----------


def test_memo_place_and_body_never_leak_into_records(client, family):
    a, b, group = family
    ua, ub = _uid(client, a), _uid(client, b)
    _event(client, a, "병원 예약", share_with=[ub], memo=SECRET, place=SECRET, start_time="09:00")
    _doc(client, a, "검진 안내", "2026-11-04T03:00:00+00:00", body=SECRET)
    got = _collect(group["id"], ua)
    assert {r.kind for r in got.records} == {"event", "document"}
    assert SECRET not in repr(got) and "비밀본문" not in repr(got)
    assert {f.name for f in SourceRecord.__dataclass_fields__.values()} == {
        "kind",
        "ref",
        "title",
        "day",
        "start_time",
    }


# ---------- 문서함 ----------


def test_document_week_boundary_in_kst(client, family):
    a, _, group = family
    _doc(client, a, "전 일요일 밤", "2026-11-01T14:59:59+00:00")
    _doc(client, a, "월요일 0시", "2026-11-01T15:00:00+00:00")
    _doc(client, a, "일요일 끝", "2026-11-08T14:59:59+00:00")
    _doc(client, a, "다음 월요일 0시", "2026-11-08T15:00:00+00:00")
    got = _collect(group["id"], _uid(client, a))
    assert sorted(r.title for r in got.records) == ["메모: 월요일 0시", "메모: 일요일 끝"]
    assert {r.title: r.day for r in got.records} == {
        "메모: 월요일 0시": date(2026, 11, 2),
        "메모: 일요일 끝": date(2026, 11, 8),
    }
    assert all(r.kind == "document" and r.start_time is None for r in got.records)


@pytest.mark.parametrize("label", ["진료 확인서", "병원 영수증", "가족관계증명서"])
def test_document_sensitive_by_label_alone_is_excluded(client, family, label):
    """`sensitivity` 를 직접 주지 않고 올려도 서비스가 종류 라벨(`SENSITIVE_WORDS`)로 민감 저장하므로 뉴스에서 빠진다."""
    a, _, group = family
    _doc(client, a, "라벨로 민감", "2026-11-04T03:00:00+00:00", label=label)
    _doc(client, a, "그냥 안내", "2026-11-04T03:00:00+00:00", label="안내문")
    with SessionLocal() as db:
        stored = db.scalar(
            select(KnowledgeItem.sensitivity).where(KnowledgeItem.title == "라벨로 민감")
        )
    assert stored == "sensitive"  # 시험 전제: 실제 저장 경로가 민감으로 판정했다
    assert _titles(_collect(group["id"], _uid(client, a)), "document") == ["안내문: 그냥 안내"]


def test_sensitive_document_is_excluded(client, family):
    a, _, group = family
    _doc(client, a, "일반 문서", "2026-11-04T03:00:00+00:00")
    _doc(client, a, "민감 문서", "2026-11-04T03:00:00+00:00", sensitivity="sensitive")
    assert _titles(_collect(group["id"], _uid(client, a)), "document") == ["메모: 일반 문서"]


def test_document_ref_is_the_item_id_and_label_is_included(client, family):
    a, _, group = family
    item_id = _doc(client, a, "독감 접종 안내", "2026-11-04T03:00:00+00:00", label="안내문")
    rec = _collect(group["id"], _uid(client, a)).records[0]
    assert (rec.ref, rec.title) == (item_id, "안내문: 독감 접종 안내")


def test_documents_are_family_shared_but_not_other_families(client, family, other_family):
    a, b, group = family
    _doc(client, a, "지민이 올린 문서", "2026-11-04T03:00:00+00:00")
    _doc(client, other_family, "남의 가족 문서", "2026-11-04T03:00:00+00:00")
    # 문서함은 가족 공유라 올린 사람과 상관없이 같은 가족이면 같은 재료다
    assert _titles(_collect(group["id"], _uid(client, b))) == ["메모: 지민이 올린 문서"]


def test_family_name_tokens_in_title_are_restored(client, family):
    a, b, group = family
    ub = _uid(client, b)
    with SessionLocal() as db:
        db.add(
            KnowledgeItem(
                group_id=group["id"],
                created_by=_uid(client, a),
                kind_label="안내문",
                title=f"[가족:{ub}] 접종 기록 [가족:ghost123]",
                body_md=SECRET,
                created_at=datetime(2026, 11, 4, 3, tzinfo=UTC),
            )
        )
        db.commit()
    got = _collect(group["id"], _uid(client, a))
    assert [r.title for r in got.records] == ["안내문: 수진 접종 기록 가족 구성원"]
    assert "[가족:" not in repr(got)


# ---------- 수집기: 미등록·준비 안 됨·예외 ----------


def _rec(kind, ref, day=date(2026, 11, 3), title="제목", start_time=None):
    return SourceRecord(kind=kind, ref=ref, title=title, day=day, start_time=start_time)


@pytest.fixture
def fake_registry(monkeypatch):
    """제공자를 비운 등록부와, 모든 기능이 준비된 가짜 스키마 상태."""
    monkeypatch.setattr(weekly_sources, "_providers", {})
    not_ready: set[str] = set()
    monkeypatch.setattr(
        weekly_sources.monitor,
        "status",
        lambda *a, **k: SimpleNamespace(feature_ready=lambda f: f not in not_ready),
    )
    return not_ready


def _register(name, records=None, owner=None, exc=None):
    def fn(db, group_id, user_id, start, end):
        if exc is not None:
            raise exc
        return list(records or [])

    weekly_sources.register_provider(name, owner or f"owner_{name}", fn)


def test_source_record_is_shared_with_evidence_module():
    assert evidence.SourceRecord is weekly_sources.SourceRecord


def test_unregistered_providers_are_unavailable(fake_registry):
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert got.records == [] and got.truncated is False
    assert got.unavailable == ["schedule", "documents"]


def test_one_unregistered_provider_keeps_the_other(fake_registry):
    _register("documents", [_rec("document", "d1")])
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert [r.ref for r in got.records] == ["d1"] and got.unavailable == ["schedule"]


def test_owner_feature_not_ready_is_unavailable_and_provider_not_called(fake_registry):
    called = []
    weekly_sources.register_provider(
        "schedule", "sched_owner", lambda *a: called.append(1) or [_rec("event", "e1")]
    )
    _register("documents", [_rec("document", "d1")], owner="docs_owner")
    fake_registry.add("sched_owner")
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert called == [] and got.unavailable == ["schedule"]
    assert [r.ref for r in got.records] == ["d1"]


def test_provider_exception_is_isolated_rolled_back_and_logged_without_body(fake_registry, caplog):
    _register("schedule", exc=RuntimeError(f"DB 오류 {SECRET}"))
    _register("documents", [_rec("document", "d1")])
    db = MagicMock()
    with caplog.at_level(logging.DEBUG):
        got = weekly_sources.collect(db, "g", "u", START, END)
    assert got.unavailable == ["schedule"] and [r.ref for r in got.records] == ["d1"]
    db.rollback.assert_called_once()
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text and "비밀본문" not in caplog.text


def test_collect_first_then_write_and_commit_survives_a_failed_provider(
    client, family, monkeypatch
):
    """계약(호출 순서): 제공자가 실패해 `collect` 가 rollback 해도, `collect` 를 먼저 하고 그 뒤에 쓰기·커밋하면 저장된다.
    (스키마 상태는 진짜를 쓰고 제공자만 가짜로 바꾼다.)"""
    a, _, group = family
    monkeypatch.setattr(weekly_sources, "_providers", {})
    _register("schedule", exc=RuntimeError("실패"), owner="schedule")
    _register("documents", [_rec("document", "d1")], owner="ai_assistant")
    with SessionLocal() as db:
        got = weekly_sources.collect(db, group["id"], _uid(client, a), START, END)
        assert got.unavailable == ["schedule"] and [r.ref for r in got.records] == ["d1"]
        db.add(
            Event(
                id="after-collect",
                group_id=group["id"],
                title="뒤에 쓴 줄",
                starts_at=datetime(2026, 11, 4, tzinfo=UTC),
                created_by=_uid(client, a),
            )
        )
        db.commit()
    assert [e.id for e in _rows("뒤에 쓴 줄")] == ["after-collect"]


def test_all_providers_failing_returns_empty_not_exception(fake_registry):
    _register("schedule", exc=ValueError("x"))
    _register("documents", exc=KeyError("y"))
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert got.records == [] and got.unavailable == ["schedule", "documents"]


def test_real_providers_report_unavailable_when_their_feature_is_not_ready(
    client, family, monkeypatch
):
    import copy

    from app.shared import schema as schema_module

    a, b, group = family
    _event(client, a, "공유 약속", share_with=[_uid(client, b)])
    _doc(client, a, "문서", "2026-11-04T03:00:00+00:00")
    real = schema_module.monitor.status

    def not_ready(feature):
        def status(*args, **kwargs):
            s = copy.deepcopy(real(*args, **kwargs))
            s.features[feature] = {"ready": False, "reason": "missing"}
            return s

        return status

    monkeypatch.setattr(schema_module.monitor, "status", not_ready("schedule"))
    got = _collect(group["id"], _uid(client, a))
    assert got.unavailable == ["schedule"] and _titles(got) == ["메모: 문서"]
    monkeypatch.setattr(schema_module.monitor, "status", not_ready("ai_assistant"))
    got = _collect(group["id"], _uid(client, a))
    assert got.unavailable == ["documents"] and _titles(got) == ["공유 약속"]


# ---------- 수집기: 입력 상한 ----------


def _many(kind, n, prefix):
    # 날짜가 늦은 것부터 넣어도 앞(이른 날짜·시간)에서 잘리는지 본다
    return [
        _rec(
            kind, f"{prefix}{i:03d}", day=date(2026, 11, 2 + (i % 7)), start_time=f"{i % 24:02d}:00"
        )
        for i in reversed(range(n))
    ]


def test_exactly_at_the_limits_is_not_truncated(fake_registry):
    _register("schedule", _many("event", 30, "e") + _many("todo", 30, "t"))
    _register("documents", _many("document", 20, "d"))
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert len(got.records) == 80 and got.truncated is False


@pytest.mark.parametrize(
    ("kind", "limit", "over"), [("event", 30, 31), ("todo", 30, 31), ("document", 20, 21)]
)
def test_one_over_the_limit_truncates_only_that_kind(fake_registry, kind, limit, over):
    others = [k for k in ("event", "todo", "document") if k != kind]
    _register("schedule", _many(kind, over, "x") + [_rec(others[0], "o1")])
    _register("documents", [_rec(others[1], "o2")])
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    assert got.truncated is True
    assert sum(1 for r in got.records if r.kind == kind) == limit
    assert {"o1", "o2"} <= {r.ref for r in got.records}  # 다른 종류는 그대로


def test_truncation_keeps_the_earliest_by_date_then_time(fake_registry):
    records = [
        _rec("document", "late", day=date(2026, 11, 8)),
        *[_rec("document", f"early{i:02d}", day=date(2026, 11, 2)) for i in range(19)],
        _rec("document", "mid", day=date(2026, 11, 5)),
        _rec("document", "mid-time", day=date(2026, 11, 2), start_time="23:00"),
    ]
    _register("documents", records)
    got = weekly_sources.collect(MagicMock(), "g", "u", START, END)
    refs = [r.ref for r in got.records]
    assert got.truncated is True and len(refs) == 20
    assert "late" not in refs and "mid" not in refs and "mid-time" in refs
    keys = [(r.day, r.start_time or "", r.ref) for r in got.records]
    assert keys == sorted(keys)  # 돌려주는 순서도 날짜·시간 순
