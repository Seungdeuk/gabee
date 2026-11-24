"""@가비 문서 도구의 올린 날(uploaded_from/to)·올린 사람(uploaded_by) 필터와 결과의 올린 날·올린 사람·원본 사진 id.

"지난달 엄마가 올린 가정통신문 뭐였지?" 같은 질문이 문서 안 날짜(occurred_on)가 아니라 올린 날·올린 사람으로 풀리게 한다.
시험 데이터는 모두 가짜다. 외부 서비스는 부르지 않는다.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.features.ai_assistant.knowledge import tools
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.shared.db import SessionLocal
from tests.helpers import allow_ai

pytestmark = pytest.mark.usefixtures("client")

K = "/ai-assistant/knowledge/items"


def _add(client, headers, title, created_at, **extra):
    r = client.post(
        K,
        json={
            "kind_label": "가정통신문",
            "title": title,
            "body_md": f"# {title}\n준비물 안내",
            **extra,
        },
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
    a, b, group = family  # a=지민(소유자), b=수진
    old_a = _add(client, a, "지민이 올린 10월", "2026-10-20T03:00:00+00:00")
    new_a = _add(client, a, "지민이 올린 11월", "2026-11-05T03:00:00+00:00")
    new_b = _add(client, b, "수진이 올린 11월", "2026-11-06T03:00:00+00:00")
    return group["id"], {"old_a": old_a, "new_a": new_a, "new_b": new_b}


def _ids(found):
    return {r["item_id"] for r in found["results"]}


def test_search_filters_by_uploaded_date_in_kst_both_ends_inclusive(client, family):
    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        nov = tools.search_knowledge(
            db, gid, "준비물 안내", top_k=10, uploaded_from="2026-11-01", uploaded_to="2026-11-30"
        )
        assert _ids(nov) == {ids["new_a"], ids["new_b"]}
        day = tools.search_knowledge(
            db, gid, "준비물 안내", top_k=10, uploaded_from="2026-11-05", uploaded_to="2026-11-05"
        )
        assert _ids(day) == {ids["new_a"]}  # 같은 날이면 그 하루만(KST 달력 날짜)


def test_search_filters_by_uploader_name(client, family):
    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        by_su = tools.search_knowledge(db, gid, "준비물 안내", top_k=10, uploaded_by="수진")
        assert _ids(by_su) == {ids["new_b"]}
        both = tools.search_knowledge(
            db, gid, "준비물 안내", top_k=10, uploaded_by="지민", uploaded_from="2026-11-01"
        )
        assert _ids(both) == {ids["new_a"]}


def test_unknown_uploader_is_reported_not_silently_ignored(client, family):
    gid, _ = _seed(client, family)
    with SessionLocal() as db:
        nobody = tools.search_knowledge(db, gid, "준비물 안내", uploaded_by="박없음")
        assert nobody["results"] == [] and "올린 사람" in nobody["note"]
        listed = tools.list_items(db, gid, uploaded_by="박없음")
        assert listed["items"] == [] and "올린 사람" in listed["note"]


def test_results_show_uploaded_date_and_uploader_name(client, family):
    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        row = next(
            r
            for r in tools.search_knowledge(db, gid, "준비물 안내", top_k=10)["results"]
            if r["item_id"] == ids["new_b"]
        )
        assert row["uploaded_on"] == "2026-11-06" and row["uploaded_by"] == "수진"
        item = next(i for i in tools.list_items(db, gid)["items"] if i["item_id"] == ids["new_a"])
        assert item["uploaded_on"] == "2026-11-05" and item["uploaded_by"] == "지민"


def test_list_items_filters_by_uploader_and_date(client, family):
    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        got = tools.list_items(db, gid, uploaded_by="지민", uploaded_from="2026-11-01")
        assert {i["item_id"] for i in got["items"]} == {ids["new_a"]}
        oct_ = tools.list_items(db, gid, uploaded_from="2026-10-01", uploaded_to="2026-10-31")
        assert {i["item_id"] for i in oct_["items"]} == {ids["old_a"]}


def test_other_family_documents_never_match(client, family, other_family):
    gid, _ = _seed(client, family)
    mine_only = _add(client, other_family, "남의 가족 문서", "2026-11-05T03:00:00+00:00")
    with SessionLocal() as db:
        found = tools.search_knowledge(db, gid, "준비물 안내", top_k=20, uploaded_from="2026-11-01")
        assert mine_only not in _ids(found)


def test_sensitive_documents_still_follow_include_sensitive(client, family):
    a, _, group = family
    sens = _add(client, a, "민감 기록", "2026-11-05T03:00:00+00:00", sensitivity="sensitive")
    with SessionLocal() as db:
        hidden = tools.search_knowledge(
            db, group["id"], "준비물 안내", uploaded_from="2026-11-01", include_sensitive=False
        )
        assert sens not in _ids(hidden)
        shown = tools.list_items(
            db, group["id"], uploaded_from="2026-11-01", include_sensitive=True
        )
        assert sens in {i["item_id"] for i in shown["items"]}


def test_original_chat_photo_id_is_included_only_when_present(client, family, monkeypatch):
    allow_ai(
        client, family[0], monkeypatch
    )  # 채팅 첨부 기록은 가족 AI 동의가 켜진 뒤 것만 외부 AI 도구에 보인다(ADR 0024)
    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        row = next(
            r
            for r in tools.search_knowledge(db, gid, "준비물 안내", top_k=10)["results"]
            if r["item_id"] == ids["new_a"]
        )
        assert row["source_attachment_id"] is None  # 직접 올린 기록은 원본 채팅 사진이 없다
        db.execute(
            update(KnowledgeItem)
            .where(KnowledgeItem.id == ids["new_a"])
            .values(source_attachment_id="att0123456789", created_at=datetime.now(UTC))
        )
        db.commit()
        linked = next(
            r
            for r in tools.search_knowledge(db, gid, "준비물 안내", top_k=10)["results"]
            if r["item_id"] == ids["new_a"]
        )
        assert linked["source_attachment_id"] == "att0123456789"
        listed = next(i for i in tools.list_items(db, gid)["items"] if i["item_id"] == ids["new_a"])
        assert listed["source_attachment_id"] == "att0123456789"


def test_main_chat_tool_runner_passes_the_new_filters(client, family):
    """AI 가 쓰는 길(rag_chat._run_tool)의 허용 인자에 올린 날·올린 사람이 들어 있어야 모델이 필터를 쓸 수 있다."""
    from app.features.ai_assistant.knowledge import rag_chat

    gid, ids = _seed(client, family)
    with SessionLocal() as db:
        found = rag_chat._run_tool(
            db,
            gid,
            "search_knowledge",
            {"query": "준비물 안내", "top_k": 10, "uploaded_by": "수진"},
        )
        assert _ids(found) == {ids["new_b"]}
        listed = rag_chat._run_tool(db, gid, "list_items", {"uploaded_from": "2026-11-06"})
        assert {i["item_id"] for i in listed["items"]} == {ids["new_b"]}


def test_non_string_uploader_is_reported_not_a_crash(client, family):
    """모델이 문자열이 아닌 값을 넘겨도 500 이 아니라 안내로 돌려준다."""
    gid, _ = _seed(client, family)
    with SessionLocal() as db:
        for bad in (["엄마"], 1, {"name": "수진"}):
            found = tools.search_knowledge(db, gid, "준비물 안내", uploaded_by=bad)
            assert found["results"] == [] and "올린 사람" in found["note"]
            listed = tools.list_items(db, gid, uploaded_by=bad)
            assert listed["items"] == [] and "올린 사람" in listed["note"]


def test_kst_day_boundaries_for_filter_and_displayed_date(client, family):
    a, _, group = family
    gid = group["id"]
    in_early = _add(client, a, "KST 11월 1일 새벽", "2026-10-31T15:30:00+00:00")
    out_before = _add(client, a, "KST 10월 31일 밤", "2026-10-31T14:59:00+00:00")
    in_late = _add(client, a, "KST 11월 30일 밤", "2026-11-30T14:59:00+00:00")
    out_after = _add(client, a, "KST 12월 1일 0시", "2026-11-30T15:00:00+00:00")
    with SessionLocal() as db:
        got = tools.list_items(
            db, gid, limit=50, uploaded_from="2026-11-01", uploaded_to="2026-11-30"
        )
        by_id = {i["item_id"]: i for i in got["items"]}
        assert set(by_id) == {in_early, in_late}
        assert by_id[in_early]["uploaded_on"] == "2026-11-01"
        assert by_id[in_late]["uploaded_on"] == "2026-11-30"
        assert out_before not in by_id and out_after not in by_id
        found = tools.search_knowledge(
            db, gid, "준비물 안내", top_k=10, uploaded_from="2026-11-01", uploaded_to="2026-11-30"
        )
        assert _ids(found) == {in_early, in_late}


def test_uploaded_on_does_not_depend_on_the_database_session_timezone():
    """PostgreSQL 은 timestamptz 를 세션 시간대로 돌려준다. 오프셋이 +09:00 인 값도 한국 날짜로 같다."""
    from datetime import timedelta, timezone
    from types import SimpleNamespace

    seoul = timezone(timedelta(hours=9))
    item = SimpleNamespace(
        created_at=datetime(2026, 11, 5, 20, 0, tzinfo=seoul),  # = 2026-11-05 11:00 UTC
        created_by="u1",
        source_attachment_id=None,
    )
    assert tools._upload_info(item, {"u1": "지민"})["uploaded_on"] == "2026-11-05"


def test_start_after_end_gives_a_note(client, family):
    gid, _ = _seed(client, family)
    with SessionLocal() as db:
        found = tools.search_knowledge(
            db, gid, "준비물 안내", uploaded_from="2026-11-30", uploaded_to="2026-11-01"
        )
        assert found["results"] == [] and "올린 날" in found["note"]
