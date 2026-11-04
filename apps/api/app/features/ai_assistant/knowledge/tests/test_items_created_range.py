"""문서 목록의 created_at 날짜 조건(created_from/created_to, KST 달력 날짜·양끝 포함)."""

from datetime import UTC, datetime

from sqlalchemy import update

from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.shared.db import SessionLocal

K = "/ai-assistant/knowledge/items"
WEEK = {"created_from": "2026-11-02", "created_to": "2026-11-08"}


def _add(client, headers, title, created_at):
    r = client.post(
        K, json={"kind_label": "메모", "title": title, "body_md": f"# {title}"}, headers=headers
    )
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        db.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == r.json()["id"])
            .values(created_at=datetime.fromisoformat(created_at).astimezone(UTC))
        )
        db.commit()


def _titles(client, headers, **params):
    r = client.get(K, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {i["title"] for i in r.json()}


def _seed(client, headers):
    _add(client, headers, "전주 일요일 밤", "2026-11-01T14:59:59+00:00")
    _add(client, headers, "월요일 0시", "2026-11-01T15:00:00+00:00")
    _add(client, headers, "다음 일요일 끝", "2026-11-08T14:59:59+00:00")
    _add(client, headers, "다음 월요일 0시", "2026-11-08T15:00:00+00:00")


def test_no_params_returns_all(client, family):
    a, _, _ = family
    _seed(client, a)
    assert len(_titles(client, a)) == 4


def test_week_boundaries_in_kst(client, family):
    a, _, _ = family
    _seed(client, a)
    assert _titles(client, a, **WEEK) == {"월요일 0시", "다음 일요일 끝"}


def test_only_one_side(client, family):
    a, _, _ = family
    _seed(client, a)
    assert _titles(client, a, created_from="2026-11-09") == {"다음 월요일 0시"}
    assert _titles(client, a, created_to="2026-11-01") == {"전주 일요일 밤"}


def test_other_family_not_mixed(client, family, other_family):
    a, _, _ = family
    _add(client, a, "우리 집", "2026-11-03T00:00:00+00:00")
    _add(client, other_family, "남의 집", "2026-11-03T00:00:00+00:00")
    assert _titles(client, a, **WEEK) == {"우리 집"}


def test_from_after_to_is_400(client, family):
    a, _, _ = family
    r = client.get(K, params={"created_from": "2026-11-09", "created_to": "2026-11-02"}, headers=a)
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_range"


def test_range_with_limit(client, family):
    a, _, _ = family
    for i in range(3):
        _add(client, a, f"항목{i}", f"2026-11-0{3 + i}T01:00:00+00:00")
    _add(client, a, "범위 밖", "2026-11-20T01:00:00+00:00")
    r = client.get(K, params={**WEEK, "limit": 2}, headers=a)
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert all(i["title"] != "범위 밖" for i in r.json())


def test_range_with_limit_keeps_newest_created(client, family):
    a, _, _ = family
    for i in range(3):
        _add(client, a, f"항목{i}", f"2026-11-0{3 + i}T01:00:00+00:00")
    r = client.get(K, params={**WEEK, "limit": 2}, headers=a)
    assert [i["title"] for i in r.json()] == [
        "항목2",
        "항목1",
    ]  # occurred_on 이 같으면 created_at 최신순


def test_one_day_range(client, family):
    a, _, _ = family
    _add(client, a, "화요일 새벽", "2026-11-02T16:00:00+00:00")  # 11/3 01:00 KST
    _add(client, a, "수요일 새벽", "2026-11-03T16:00:00+00:00")  # 11/4 01:00 KST
    assert _titles(client, a, created_from="2026-11-03", created_to="2026-11-03") == {"화요일 새벽"}


def test_extreme_dates_are_400_not_500(client, family):
    a, _, _ = family
    for params in ({"created_to": "9999-12-31"}, {"created_from": "0001-01-01"}):
        r = client.get(K, params=params, headers=a)
        assert r.status_code == 400, (params, r.text)
        assert r.json()["code"] == "invalid_range"


def test_bad_date_format_is_422(client, family):
    a, _, _ = family
    r = client.get(K, params={"created_from": "2026-13-45"}, headers=a)
    assert r.status_code == 422


def test_uses_configured_offset(client, family, monkeypatch):
    from app.shared.config import settings

    a, _, _ = family
    _add(client, a, "UTC 새벽", "2026-11-03T01:00:00+00:00")  # 11/3 10:00 KST, 11/3 01:00 UTC
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 0)
    assert _titles(client, a, created_from="2026-11-03", created_to="2026-11-03") == {"UTC 새벽"}
    _add(client, a, "UTC 전날 밤", "2026-11-02T23:00:00+00:00")  # offset 0 이면 11/2
    assert _titles(client, a, created_from="2026-11-03", created_to="2026-11-03") == {"UTC 새벽"}
