"""search_knowledge 의 item_id: 한 문서 안에서만 찾기(해당 문서만, 점수 순, 다른 그룹·없는 id 차단, 도구 정의)."""

import pytest

from app.features.ai_assistant.knowledge import tools
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")


def _add(client, headers, **kw):
    r = client.post("/ai-assistant/knowledge/items", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _long_body(title: str, needle: str) -> str:
    filler = "\n".join(
        f"[p.{n}]\n일반 안내 문장입니다 항목 {n} " + "가나다라마바사 " * 60 for n in range(1, 41)
    )
    return f"# {title}\n{filler}\n[p.41]\n{needle}"


@pytest.fixture
def docs(client, family):
    a, _, group = family
    big = _add(
        client,
        a,
        kind_label="규정집",
        title="긴 규정집",
        body_md=_long_body("긴 규정집", "배수필터 청소 주기는 한 달에 한 번입니다."),
    )
    other = _add(
        client,
        a,
        kind_label="설명서",
        title="세탁기 설명서",
        body_md="# 세탁기 설명서\n[p.1]\n배수필터는 한 달에 한 번 청소합니다.",
    )
    return a, group, big, other


def test_item_id_returns_only_that_document_in_score_order(docs):
    _, group, big, other = docs
    with SessionLocal() as db:
        found = tools.search_knowledge(
            db, group["id"], "배수필터 청소 주기", top_k=20, item_id=big["id"]
        )
    results = found["results"]
    assert 1 < len(results) <= tools.IN_ITEM_MAX_TOP_K  # 최대 8
    assert {r["item_id"] for r in results} == {big["id"]}
    assert "배수필터" in results[0]["text"]  # 뒤쪽 정답 조각이 위로 올라온다(쪽 순서 아님)
    assert results[0]["page"] != results[-1]["page"]


def test_item_id_default_top_k_is_five(docs):
    _, group, big, _ = docs
    with SessionLocal() as db:
        found = tools.search_knowledge(db, group["id"], "안내 문장", item_id=big["id"])
    assert len(found["results"]) == 5


def test_other_group_item_id_is_blocked(client, docs, other_family):
    a, group, _, _ = docs
    secret = _add(
        client,
        other_family,
        kind_label="고지서",
        title="남의 비밀 문서",
        body_md="# 남의 비밀 문서\n배수필터 청소 비밀 내용",
    )
    with SessionLocal() as db:
        found = tools.search_knowledge(db, group["id"], "배수필터 청소", item_id=secret["id"])
    assert found["results"] == [] and "찾지 못" in found["note"]
    assert "비밀" not in str(found)


def test_unknown_item_id_gives_empty_result_with_note(docs):
    _, group, _, _ = docs
    with SessionLocal() as db:
        found = tools.search_knowledge(db, group["id"], "배수필터", item_id="no-such-id")
    assert found["results"] == [] and "item_id" in found["note"]


def test_sensitive_item_is_hidden_when_not_allowed(client, family):
    a, _, group = family
    item = _add(
        client,
        a,
        kind_label="약국 처방전",
        title="처방전",
        body_md="# 처방전\n소염진통제 복용",
        sensitivity="sensitive",
    )
    with SessionLocal() as db:
        shown = tools.search_knowledge(db, group["id"], "소염진통제", item_id=item["id"])
        hidden = tools.search_knowledge(
            db, group["id"], "소염진통제", item_id=item["id"], include_sensitive=False
        )
    assert shown["results"] and hidden["results"] == []


def test_tool_spec_and_get_item_note_mention_item_id(client, family):
    spec = next(t for t in tools.TOOL_SPECS if t["name"] == "search_knowledge")
    assert spec["input_schema"]["properties"]["item_id"]["type"] == "string"
    assert "item_id" not in spec["input_schema"]["required"]
    a, _, group = family
    big = _add(
        client, a, kind_label="규정집", title="긴 문서", body_md="# 긴 문서\n" + "가" * 13000
    )
    with SessionLocal() as db:
        out = tools.get_item(db, group["id"], big["id"])
    assert "item_id 와 구체적인 낱말" in out["note"]
