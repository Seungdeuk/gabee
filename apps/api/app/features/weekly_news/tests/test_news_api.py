"""주간 가족 뉴스 읽기 API(`GET /report/news`)·새 표 시험.

LLM·네트워크 호출은 하지 않는다(부르면 시험이 실패한다). 시간은 의존성 `current_time` 으로 고정한다(KST = UTC+9).
저장본은 시험이 DB 에 직접 넣는다(생성은 T26-b).
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.features.weekly_news import router as news_router
from app.features.weekly_news.models import MemberWeeklyNews
from app.main import app
from app.shared import group_purge
from app.shared.config import settings
from app.shared.db import SessionLocal, engine
from app.shared.schema import feature_tables, monitor

URL = "/report/news"
THIS_MON = date(2026, 11, 9)
LAST_MON = date(2026, 11, 2)
WED = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)  # 수요일 12:00 KST
SUN_1759 = datetime(2026, 11, 15, 8, 59, tzinfo=UTC)  # 일요일 17:59 KST
SUN_1800 = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)  # 일요일 18:00 KST

BODY = {
    "title": "이번 주 우리 가족",
    "items": [{"text": "치과 진료를 다녀왔어요", "source_ids": ["e1"]}],
}
SOURCES = [
    {"id": "e1", "kind": "event", "ref": "ev123", "label": "치과", "date": "2026-11-03"},
]


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    """읽기 API 는 외부 호출을 하지 않는다: httpx 가 불리면 실패한다."""

    def boom(*args, **kwargs):
        raise AssertionError("읽기 API 가 외부 호출을 했다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)


@pytest.fixture
def at():
    """`at(now)` 로 서버의 현재 시각을 고정한다."""

    def set_now(now: datetime) -> None:
        app.dependency_overrides[news_router.current_time] = lambda: now

    set_now(WED)
    yield set_now
    app.dependency_overrides.pop(news_router.current_time, None)


def _ids(client, headers) -> tuple[str, str]:
    me = client.get("/family-group/me", headers=headers).json()
    return me["id"], me["active_group_id"]


def _save(user_id: str, group_id: str, week: date, status: str = "ok", **fields) -> None:
    now = datetime.now(UTC)
    values = {"created_at": now, "updated_at": now, **fields}  # fields 가 시각을 덮어쓸 수 있다
    row = MemberWeeklyNews(
        id=uuid.uuid4().hex,
        group_id=group_id,
        user_id=user_id,
        week_start=week,
        status=status,
        **values,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()


def _ok(**over):
    data = {
        "body": BODY,
        "sources": SOURCES,
        "model": "test-model",
        "prompt_version": "v1",
        "input_tokens": 100,
        "output_tokens": 50,
    }
    data.update(over)
    return data


# ── 저장본이 없을 때 ───────────────────────────────────────────


def test_no_saved_news_is_not_generated_and_makes_no_outbound_call(client, family, at):
    a, _, _ = family
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "not_generated"
    assert body["week_start"] == "2026-11-02" and body["week_end"] == "2026-11-08"
    assert body["title"] is None and body["items"] == [] and body["sources"] == []
    assert body["generated_at"] is None and body["ai_generated"] is False
    assert body["model"] is None
    with SessionLocal() as db:  # 읽기는 아무것도 만들지 않는다
        assert db.execute(text("SELECT count(*) FROM member_weekly_news")).scalar() == 0


def test_default_week_is_this_weeks_monday(client, family, at):
    a, _, _ = family
    body = client.get(URL, headers=a).json()
    assert body["week_start"] == "2026-11-09" and body["status"] == "too_early"


# ── 저장본 매핑 ────────────────────────────────────────────────


def test_saved_ok_news_is_returned_without_internal_fields(client, family, at):
    a, _, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, LAST_MON, **_ok(error_code=None))
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready" and body["ai_generated"] is True
    assert body["title"] == "이번 주 우리 가족"
    assert body["items"] == [{"text": "치과 진료를 다녀왔어요", "source_ids": ["e1"]}]
    assert body["sources"] == [
        {"id": "e1", "kind": "event", "ref": "ev123", "label": "치과", "date": "2026-11-03"}
    ]
    assert body["model"] == "test-model" and body["generated_at"]
    assert set(body) == {
        "status", "week_start", "week_end", "title", "items", "sources",
        "generated_at", "ai_generated", "model",
    }  # fmt: skip
    assert "prompt_version" not in r.text and "input_tokens" not in r.text
    assert "error_code" not in r.text


@pytest.mark.parametrize(
    "db_status,expected,fields",
    [
        # 시험의 현재(WED)보다 방금 시작한 pending 은 만드는 중으로 보인다(5분 넘은 pending 은 not_generated, test_generate 에서 본다)
        ("pending", "pending", {"updated_at": WED - timedelta(seconds=30)}),
        ("failed", "failed", {"error_code": "llm_error"}),
        ("empty", "empty", {}),
    ],
)
def test_other_saved_statuses_are_mapped(client, family, at, db_status, expected, fields):
    a, _, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, LAST_MON, status=db_status, **fields)
    body = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a).json()
    assert body["status"] == expected
    assert body["items"] == [] and body["title"] is None and body["ai_generated"] is False
    assert "llm_error" not in str(body)


def test_saved_row_wins_even_when_this_week_is_not_ready(client, family, at):
    a, _, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, THIS_MON, **_ok())  # 이번 주인데 이미 저장본이 있다(수요일)
    assert client.get(URL, headers=a).json()["status"] == "ready"


# ── 본인만 ────────────────────────────────────────────────────


def test_only_the_owner_sees_the_saved_news(client, family, other_family, at):
    a, b, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, LAST_MON, **_ok())
    params = {"week_start": LAST_MON.isoformat()}
    assert client.get(URL, params=params, headers=a).json()["status"] == "ready"
    # 같은 가족의 다른 구성원
    assert client.get(URL, params=params, headers=b).json()["status"] == "not_generated"
    # 다른 가족
    other = client.get(URL, params=params, headers=other_family)
    assert other.json()["status"] == "not_generated"
    for r in (client.get(URL, params=params, headers=b), other):
        assert "치과" not in r.text and "ev123" not in r.text


def test_same_user_in_another_group_row_is_not_returned(client, family, at):
    """조회 키는 (현재 가족, 본인, 주): 같은 사람의 다른 가족 저장본은 현재 가족에서 보이지 않는다."""
    a, _, group = family
    uid, gid = _ids(client, a)
    other_group = client.post("/family-group/groups", json={"name": "두 번째"}, headers=a)
    assert other_group.status_code in (200, 201), other_group.text
    new_gid = client.get("/family-group/me", headers=a).json()["active_group_id"]
    assert new_gid != gid
    _save(uid, gid, LAST_MON, **_ok())  # 옛 가족의 저장본
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=a)
    assert r.json()["status"] == "not_generated"


# ── 주 검증 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "week_start",
    [
        "2026-11-10",  # 월요일이 아님
        "2026-11-16",  # 미래 주
        "2026-09-07",  # 9주 전
        "not-a-date",
    ],
)
def test_invalid_week_is_400(client, family, at, week_start):
    a, _, _ = family
    r = client.get(URL, params={"week_start": week_start}, headers=a)
    if week_start == "not-a-date":
        assert r.status_code == 422
    else:
        assert r.status_code == 400 and r.json()["code"] == "invalid_week", r.text
        assert week_start not in r.text


def test_eight_weeks_back_is_allowed(client, family, at):
    a, _, _ = family
    r = client.get(URL, params={"week_start": "2026-09-14"}, headers=a)
    assert r.status_code == 200 and r.json()["status"] == "not_generated"


# ── 이번 주 생성 시점 ─────────────────────────────────────────


def test_this_week_before_sunday_1800_is_too_early(client, family, at):
    a, _, _ = family
    at(SUN_1759)
    assert client.get(URL, headers=a).json()["status"] == "too_early"


def test_this_week_from_sunday_1800_is_not_generated(client, family, at):
    a, _, _ = family
    at(SUN_1800)
    assert client.get(URL, headers=a).json()["status"] == "not_generated"


# ── 표 ────────────────────────────────────────────────────────


def test_unique_per_group_user_week(client, family):
    a, _, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, LAST_MON)
    with pytest.raises(IntegrityError):
        _save(uid, gid, LAST_MON)
    _save(uid, gid, THIS_MON)  # 다른 주는 된다


def test_json_columns_round_trip(client, family):
    a, _, _ = family
    uid, gid = _ids(client, a)
    _save(uid, gid, LAST_MON, **_ok())
    with SessionLocal() as db:
        row = db.query(MemberWeeklyNews).one()
        assert row.body == BODY and row.sources == SOURCES
        assert row.week_start == LAST_MON and row.status == "ok"


def test_purge_group_deletes_news_rows(client, family):
    a, b, _ = family
    uid, gid = _ids(client, a)
    buid, _ = _ids(client, b)
    _save(uid, gid, LAST_MON, **_ok())
    _save(buid, gid, LAST_MON, **_ok())
    with SessionLocal() as db:
        group_purge.purge_group(db, gid)
        db.commit()
        assert db.query(MemberWeeklyNews).count() == 0


def test_purge_group_keeps_other_groups_news(client, family, other_family):
    a, _, _ = family
    uid, gid = _ids(client, a)
    oid, ogid = _ids(client, other_family)
    _save(uid, gid, LAST_MON)
    _save(oid, ogid, LAST_MON)
    with SessionLocal() as db:
        group_purge.purge_group(db, gid)
        db.commit()
        rows = db.query(MemberWeeklyNews).all()
        assert [r.group_id for r in rows] == [ogid]


# ── 스키마 게이트 ─────────────────────────────────────────────


def test_news_table_belongs_to_weekly_news_feature():
    assert "member_weekly_news" in feature_tables()["weekly_news"]


def test_missing_table_is_503_for_news_only(client, family, at, monkeypatch):
    a, _, _ = family
    for name in ("schema_recheck_ready_seconds", "schema_recheck_not_ready_seconds"):
        monkeypatch.setattr(settings, name, 0)
    monkeypatch.setattr(settings, "schema_force_min_interval_seconds", 0)
    monitor.reset()
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE member_weekly_news"))
        r = client.get(URL, headers=a)
        assert r.status_code == 503 and r.json()["code"] == "schema_not_ready", r.text
        assert client.get("/schedule/events", headers=a).status_code == 200
        assert client.get("/family-group/me", headers=a).status_code == 200
        report = client.get("/health/db").json()
        assert report["features"]["weekly_news"] == {"ready": False, "reason": "missing_schema"}
        assert report["features"]["schedule"]["ready"] is True
    finally:
        monitor.reset()


# ── 저장된 JSON 이 깨졌을 때(수동 수정·버그·옛 형식)는 500 이 아니라 failed ─────────


@pytest.mark.parametrize(
    "fields",
    [
        {"body": ["문자열이 아니라 목록"], "sources": []},
        {"body": "그냥 문자열", "sources": []},
        {"body": {"title": 1, "items": []}, "sources": []},
        {"body": {"title": "제목", "items": "목록 아님"}, "sources": []},
        {"body": {"title": "제목", "items": [{"text": "글"}]}, "sources": []},
        {"body": {"title": "제목", "items": [1, 2]}, "sources": []},
        {"body": BODY, "sources": "목록 아님"},
        {"body": BODY, "sources": [{"id": "e1"}]},
        {"body": BODY, "sources": [{"id": "e1", "kind": "alien", "ref": "r", "label": "l"}]},
    ],
)
def test_corrupt_saved_json_is_failed_not_500(client, family, fields):
    headers, _, _ = family
    user_id, group_id = _ids(client, headers)
    _save(user_id, group_id, LAST_MON, status="ok", model="m", **fields)
    r = client.get(URL, params={"week_start": LAST_MON.isoformat()}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed"
    assert r.json()["items"] == [] and r.json()["sources"] == []
