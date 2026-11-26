"""키워드 찾기(POST /ai-assistant/knowledge/find)의 올린 날·올린 사람 필터와 결과의 올린 날·올린 사람·원본 사진 id (T23 P-06).

의미 검색 도구(#393)와 같은 뜻: 올린 날은 한국 날짜 양끝 포함, 올린 사람은 가족 이름으로 찾는다.
시험 데이터는 모두 가짜다. LLM·외부 서비스는 부르지 않는다.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.features.ai_assistant.knowledge import service
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

K = "/ai-assistant/knowledge"
Q = "준비물 안내"


def _add(client, headers, title, created_at, **extra):
    r = client.post(
        f"{K}/items",
        json={"kind_label": "가정통신문", "title": title, "body_md": f"# {title}\n{Q}", **extra},
        headers=headers,
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


def _seed(client, family):
    a, b, _ = family  # a=지민(소유자), b=수진
    return {
        "old_a": _add(client, a, "지민이 올린 10월", "2026-10-20T03:00:00+00:00"),
        "new_a": _add(client, a, "지민이 올린 11월", "2026-11-05T03:00:00+00:00"),
        "new_b": _add(client, b, "수진이 올린 11월", "2026-11-06T03:00:00+00:00"),
    }


def _post(client, headers, **extra):
    return client.post(f"{K}/find", json={"query": Q, "limit": 30, **extra}, headers=headers)


def _ids(client, headers, **extra):
    r = _post(client, headers, **extra)
    assert r.status_code == 200, r.text
    return {h["item_id"] for h in r.json()["hits"]}


def test_no_filter_keeps_old_behavior(client, family):
    ids = _seed(client, family)
    assert _ids(client, family[0]) == set(ids.values())


def test_filters_by_uploader_name(client, family):
    ids = _seed(client, family)
    assert _ids(client, family[0], uploaded_by="수진") == {ids["new_b"]}
    assert _ids(client, family[0], uploaded_by="지민") == {ids["old_a"], ids["new_a"]}


def test_filters_by_uploaded_date_inclusive(client, family):
    ids = _seed(client, family)
    a = family[0]
    nov = _ids(client, a, uploaded_from="2026-11-01", uploaded_to="2026-11-30")
    assert nov == {ids["new_a"], ids["new_b"]}
    assert _ids(client, a, uploaded_from="2026-11-05", uploaded_to="2026-11-05") == {ids["new_a"]}
    assert _ids(client, a, uploaded_to="2026-10-31") == {ids["old_a"]}


def test_combined_uploader_and_date(client, family):
    ids = _seed(client, family)
    got = _ids(client, family[0], uploaded_by="지민", uploaded_from="2026-11-01")
    assert got == {ids["new_a"]}


def test_kst_day_boundaries(client, family):
    a = family[0]
    in_early = _add(client, a, "KST 11월 1일 새벽", "2026-10-31T15:30:00+00:00")
    out_before = _add(client, a, "KST 10월 31일 밤", "2026-10-31T14:59:00+00:00")
    in_late = _add(client, a, "KST 11월 30일 밤", "2026-11-30T14:59:00+00:00")
    out_after = _add(client, a, "KST 12월 1일 0시", "2026-11-30T15:00:00+00:00")
    r = _post(client, a, uploaded_from="2026-11-01", uploaded_to="2026-11-30")
    by_id = {h["item_id"]: h for h in r.json()["hits"]}
    assert set(by_id) == {in_early, in_late}
    assert by_id[in_early]["uploaded_on"] == "2026-11-01"
    assert by_id[in_late]["uploaded_on"] == "2026-11-30"
    assert out_before not in by_id and out_after not in by_id


def test_unknown_uploader_is_a_clear_error(client, family):
    _seed(client, family)
    r = _post(client, family[0], uploaded_by="박없음")
    assert r.status_code == 422
    assert r.json()["code"] == "unknown_uploader" and "올린 사람" in r.json()["message"]


def test_bad_uploader_and_date_formats_are_rejected(client, family):
    a = family[0]
    assert _post(client, a, uploaded_by=["수진"]).status_code == 422
    assert _post(client, a, uploaded_from="11월 1일").status_code == 422
    r = _post(client, a, uploaded_from="2026-11-30", uploaded_to="2026-11-01")
    assert r.status_code == 400 and r.json()["code"] == "invalid_range"


def test_blank_uploader_means_no_filter(client, family):
    ids = _seed(client, family)
    assert _ids(client, family[0], uploaded_by="  ") == set(ids.values())


def test_other_family_items_never_returned(client, family, other_family):
    ids = _seed(client, family)
    theirs = _add(client, other_family, "남의 가족 문서", "2026-11-05T03:00:00+00:00")
    got = _ids(client, family[0], uploaded_from="2026-11-01")
    assert theirs not in got and got == {ids["new_a"], ids["new_b"]}
    # 다른 가족 구성원 이름으로는 올린 사람을 찾을 수 없다(그 가족의 구성원 목록만 본다)
    assert _post(client, other_family, uploaded_by="수진").status_code == 422


def test_hits_show_uploaded_date_uploader_and_attachment(client, family):
    ids = _seed(client, family)
    with SessionLocal() as db:
        db.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == ids["new_a"])
            .values(source_attachment_id="att0123456789")
        )
        db.commit()
    hits = {h["item_id"]: h for h in _post(client, family[0]).json()["hits"]}
    assert hits[ids["new_b"]]["uploaded_on"] == "2026-11-06"
    assert hits[ids["new_b"]]["uploaded_by"] == "수진"
    assert hits[ids["new_b"]]["source_attachment_id"] is None
    assert hits[ids["new_a"]]["uploaded_by"] == "지민"
    assert hits[ids["new_a"]]["source_attachment_id"] == "att0123456789"


def test_semantic_fallback_gets_the_same_filters(client, family, monkeypatch):
    _seed(client, family)
    seen = {}

    def fake_search(*args, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(service, "search", fake_search)
    r = client.post(
        f"{K}/find",
        json={
            "query": "없는말씀",
            "semantic": True,
            "uploaded_by": "수진",
            "uploaded_from": "2026-11-01",
            "uploaded_to": "2026-11-30",
        },
        headers=family[0],
    )
    assert r.status_code == 200 and r.json()["method"] == "semantic"
    assert seen["created_from"] == datetime(2026, 10, 31, 15, tzinfo=UTC)
    assert seen["created_to"] == datetime(2026, 11, 30, 15, tzinfo=UTC)
    assert len(seen["created_by"]) == 1


def test_search_route_response_is_unchanged(client, family):
    """/search 는 같은 HitOut 을 쓰지만 이번 변경으로 응답 칸이 늘지 않는다."""
    _seed(client, family)
    r = client.post(f"{K}/search", json={"query": Q}, headers=family[0])
    assert r.status_code == 200
    for h in r.json()["hits"]:
        assert "uploaded_by" not in h and "source_attachment_id" not in h
