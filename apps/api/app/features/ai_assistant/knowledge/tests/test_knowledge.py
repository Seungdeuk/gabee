"""기록 저장·검색. 전처리 없이 같은 모양의 가짜 마크다운 기록을 직접 넣어서 확인한다."""

from datetime import date
from pathlib import Path

import pytest

from app.features.ai_assistant.knowledge import embedding, rag_chat, service, tools
from app.features.ai_assistant.knowledge.chunking import split_markdown
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm.chat_model import LAST_CALL_NOTE
from tests.helpers import signup

BILL = """# 2026년 10월 전기요금 고지서
분류: 전기요금 고지서
- 고객명 엄마
- 사용량 312 kWh
- 청구금액 48,200원
- 납기일 2026-10-25"""
WATER = """# 10월 상하수도 요금 고지서
분류: 수도요금 고지서
- 사용량 18톤
- 상하수도 요금 23,400원"""
RX = """# 엄마 관절염 약 처방전
분류: 약국 처방전
- 소염진통제 3종 7일분
[읽지 못한 부분]"""


def _add(client, headers, **kw):
    r = client.post("/ai-assistant/knowledge/items", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def seeded(client, family):
    a, b, group = family
    bill = _add(
        client,
        a,
        kind_label="전기요금 고지서",
        title="10월 전기요금",
        body_md=BILL,
        occurred_on="2026-10-01",
        source_path="/files/2026/10/bill1.jpg",  # 요청으로는 저장되지 않는다(서버가 만든 참조만)
    )
    assert bill["source_path"] is None
    from app.features.ai_assistant.knowledge.models import KnowledgeItem

    with SessionLocal() as db:  # 서버가 만든 원본 참조는 업로드 처리가 넣는다. 여기서는 직접 넣는다
        db.get(KnowledgeItem, bill["id"]).source_path = "/files/2026/10/bill1.jpg"
        db.commit()
    _add(
        client,
        a,
        kind_label="수도요금 고지서",
        title="10월 수도요금",
        body_md=WATER,
        occurred_on="2026-10-03",
    )
    _add(
        client,
        a,
        kind_label="약국 처방전",
        title="엄마 처방전",
        body_md=RX,
        occurred_on="2026-09-20",
    )
    return a, b, group


def test_chunking_keeps_header_and_splits_pages_and_slides():
    md = "# 여행 계획\n분류: 발표자료\n[p.1]\n개요 줄\n[p.2]\n일정 줄\n## 슬라이드 3 · 맛집\n식당 목록"
    chunks = split_markdown(md)
    assert [c.page_label for c in chunks] == ["p.1", "p.2", "슬라이드 3 · 맛집"]
    assert all(c.text.startswith("# 여행 계획\n분류: 발표자료") for c in chunks)
    assert [c.seq for c in chunks] == [0, 1, 2]


def test_chunking_splits_long_text_and_keeps_title_only_records():
    long_md = "# 긴 문서\n분류: 계약서\n" + "\n".join(
        f"{i}번째 조항 내용입니다" * 5 for i in range(80)
    )
    chunks = split_markdown(long_md, max_chars=300)
    assert len(chunks) > 3 and all(len(c.text) <= 300 for c in chunks)
    only_title = split_markdown("# 사진\n분류: 풍경 사진")
    assert len(only_title) == 1 and "풍경 사진" in only_title[0].text


def test_ingest_marks_unread_parts_and_sensitive_kinds(client, family):
    a, _, _ = family
    rx = _add(client, a, kind_label="약국 처방전", title="처방전", body_md=RX)
    assert rx["has_unread_parts"] is True and rx["sensitivity"] == "sensitive"
    bill = _add(client, a, kind_label="전기요금 고지서", title="전기", body_md=BILL)
    assert bill["has_unread_parts"] is False and bill["sensitivity"] == "normal"
    forced = _add(
        client, a, kind_label="전기요금 고지서", title="전기", body_md=BILL, sensitivity="sensitive"
    )
    assert forced["sensitivity"] == "sensitive"


def test_search_finds_the_right_record_with_source(client, seeded):
    a, _, _ = seeded
    r = client.post("/ai-assistant/knowledge/search", json={"query": "전기요금 얼마"}, headers=a)
    hits = r.json()["hits"]
    assert hits[0]["kind_label"] == "전기요금 고지서"
    assert hits[0]["source_path"] == "/files/2026/10/bill1.jpg"
    assert "48,200원" in hits[0]["snippet"]
    r = client.post(
        "/ai-assistant/knowledge/search", json={"query": "수도 요금", "top_k": 1}, headers=a
    )
    assert [h["kind_label"] for h in r.json()["hits"]] == ["수도요금 고지서"]


def test_search_filters_by_kind_and_date(client, seeded):
    a, _, _ = seeded
    r = client.post(
        "/ai-assistant/knowledge/search",
        json={"query": "고지서", "kind_label": "수도요금 고지서"},
        headers=a,
    )
    assert {h["kind_label"] for h in r.json()["hits"]} == {"수도요금 고지서"}
    r = client.post(
        "/ai-assistant/knowledge/search",
        json={"query": "기록", "date_from": "2026-10-01"},
        headers=a,
    )
    assert {h["title"] for h in r.json()["hits"]} == {"10월 전기요금", "10월 수도요금"}
    r = client.post(
        "/ai-assistant/knowledge/search",
        json={"query": "처방", "include_sensitive": False},
        headers=a,
    )
    assert all(h["sensitivity"] == "normal" for h in r.json()["hits"])


def test_other_family_group_never_sees_records(client, seeded):
    a, b, _ = seeded
    stranger = signup(client, "철수")
    client.post("/family-group/groups", json={"name": "남의 가족"}, headers=stranger)
    r = client.post("/ai-assistant/knowledge/search", json={"query": "전기요금"}, headers=stranger)
    assert r.json()["hits"] == []
    item_id = client.get("/ai-assistant/knowledge/items", headers=a).json()[0]["id"]
    assert (
        client.get(f"/ai-assistant/knowledge/items/{item_id}", headers=stranger).status_code == 404
    )
    assert client.get("/ai-assistant/knowledge/items", headers=stranger).json() == []
    # 같은 그룹 구성원은 본다
    assert client.get(f"/ai-assistant/knowledge/items/{item_id}", headers=b).status_code == 200


def test_validation_and_errors(client, family):
    a, _, _ = family
    assert (
        client.post("/ai-assistant/knowledge/search", json={"query": ""}, headers=a).status_code
        == 422
    )
    bad = {"kind_label": "x", "title": "x", "body_md": ""}
    assert client.post("/ai-assistant/knowledge/items", json=bad, headers=a).status_code == 422
    r = client.get("/ai-assistant/knowledge/items/없는id", headers=a)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert client.post("/ai-assistant/knowledge/search", json={"query": "a"}).status_code == 401


def test_reindex_after_model_change(client, seeded):
    a, _, group = seeded

    class OtherEmbedder(embedding.HashingEmbedder):
        dim = 128

        def __init__(self) -> None:
            self.name = "other-128"

    old = embedding.get_embedder()
    embedding.set_embedder(OtherEmbedder())
    try:
        # 모델이 바뀌면 이전 벡터는 후보에서 빠지므로 다시 만들기 전에는 찾지 못한다
        r = client.post("/ai-assistant/knowledge/search", json={"query": "전기요금"}, headers=a)
        assert r.json()["hits"] == []
        with SessionLocal() as db:
            assert service.reindex(db, group["id"]) >= 3
        r = client.post("/ai-assistant/knowledge/search", json={"query": "전기요금"}, headers=a)
        assert r.json()["hits"][0]["kind_label"] == "전기요금 고지서"
    finally:
        embedding.set_embedder(old)


def test_demo_seed_answers_typical_chat_questions(client, family):
    from app.features.ai_assistant.knowledge.seed import DEMO, seed_demo

    _, _, group = family
    with SessionLocal() as db:
        user_id = db.scalar(__import__("sqlalchemy").text("select id from users limit 1"))
        assert seed_demo(db, group["id"], user_id) == len(DEMO)
        for question, expected in [
            ("이번 달 전기요금", "전기요금 고지서"),
            # 낱말이 다른 질문("비행기 몇 시")은 해시 임베더로는 못 찾는다. 실제 모델을 붙일 때 확인한다.
            ("제주 항공권 예약", "항공권 예약 확인서"),
            ("월세 계약서 보증금", "임대차 계약서"),
            ("아빠 혈압약", "병원 진료 내역서"),
        ]:
            top = tools.search_knowledge(db, group["id"], question, top_k=3)["results"]
            assert expected in [r["kind_label"] for r in top], question


def test_llm_tools_shape(client, seeded):
    _, _, group = seeded
    assert [t["name"] for t in tools.TOOL_SPECS] == [
        "search_knowledge",
        "get_item",
        "list_items",
        "list_name_checks",
        "resolve_name_check",
        "resolve_reminder",
        "set_reminders",
    ]
    with SessionLocal() as db:
        found = tools.search_knowledge(db, group["id"], "엄마 약 처방")
        top = found["results"][0]
        assert top["kind_label"] == "약국 처방전" and top["has_unread_parts"] is True
        assert top["sensitive"] is True and "has_unread_parts" in found["note"]
        full = tools.get_item(db, group["id"], top["item_id"])
        assert "소염진통제" in full["text"]
        listed = tools.list_items(db, group["id"], kind_label="전기요금 고지서")
        assert [i["title"] for i in listed["items"]] == ["10월 전기요금"]
        ranged = tools.search_knowledge(db, group["id"], "기록", date_from="2026-10-01")
        assert len(ranged["results"]) == 2
    assert date.fromisoformat("2026-10-01")


def test_ask_runs_tool_loop_and_cannot_choose_the_group(client, seeded):
    _, _, group = seeded
    calls = []

    def fake_post(body):
        calls.append(body)
        if len(calls) == 1:
            # LLM 이 다른 그룹 id 를 넘겨도 무시되어야 한다
            args = {"query": "전기요금", "group_id": "남의그룹"}
            return {
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "search_knowledge", "input": args}
                ]
            }
        result = body["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and "48,200원" in result["content"]
        return {"content": [{"type": "text", "text": "10월 전기요금은 48,200원이에요."}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "이번 달 전기요금", post=fake_post)
    assert r.source == "ai" and "48,200원" in r.answer
    assert (
        r.sources[0]["title"] == "10월 전기요금" and r.tool_calls[0]["name"] == "search_knowledge"
    )
    assert calls[0]["tools"] == tools.TOOL_SPECS and "search_knowledge" in calls[0]["system"]


def test_ask_survives_unknown_tool_and_stops_runaway_loops(client, seeded):
    _, _, group = seeded
    seen = []

    def bad_then_answer(body):
        seen.append(body)
        if len(seen) == 1:
            return {
                "content": [{"type": "tool_use", "id": "t1", "name": "delete_all", "input": {}}]
            }
        assert body["messages"][-1]["content"][0]["is_error"] is True
        return {"content": [{"type": "text", "text": "그건 할 수 없어요."}]}

    def forever(body):
        return {"content": [{"type": "tool_use", "id": "t", "name": "list_items", "input": {}}]}

    with SessionLocal() as db:
        assert rag_chat.ask(db, group["id"], "다 지워줘", post=bad_then_answer).answer
        stuck = rag_chat.ask(db, group["id"], "전기요금", post=forever)
    assert stuck.source == "fallback" and stuck.sources


def test_ask_endpoint_falls_back_without_api_key(client, seeded):
    a, _, _ = seeded
    r = client.post("/ai-assistant/knowledge/ask", json={"question": "수도요금 얼마"}, headers=a)
    body = r.json()
    assert r.status_code == 200 and body["source"] == "fallback"
    assert body["sources"][0]["kind_label"] == "수도요금 고지서"
    assert (
        client.post("/ai-assistant/knowledge/ask", json={"question": ""}, headers=a).status_code
        == 422
    )


def test_ask_lists_only_records_the_answer_mentions(client, seeded):
    _, _, group = seeded
    steps = []

    def fake_post(body):
        steps.append(1)
        if len(steps) == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t",
                        "name": "search_knowledge",
                        "input": {"query": "고지서"},
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "「10월 수도요금」 고지서는 23,400원이에요."}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "수도요금", post=fake_post)
    assert [s["title"] for s in r.sources] == ["10월 수도요금"]


MODEL_DIR = Path(__file__).resolve().parents[5] / "data" / "models" / "e5-small-ft"


@pytest.mark.skipif(not (MODEL_DIR / "model.onnx").exists(), reason="서버 PC 모델 파일이 없는 환경")
def test_real_onnx_model_understands_meaning_beyond_words():
    e = embedding.OnnxE5Embedder(MODEL_DIR)
    water = "# 10월 상하수도 요금 고지서\n분류: 수도요금 고지서\n- 상하수도 요금 23,400원"
    power = "# 10월 전기요금 고지서\n분류: 전기요금 고지서\n- 청구금액 48,200원"
    pw, pp = e.embed_passages([water, power])
    q = e.embed_query("물값 얼마 나왔어")  # 같은 낱말이 거의 없는 질문
    assert len(q) == e.dim == 384 and abs(embedding.cosine(q, q) - 1) < 1e-3
    assert embedding.cosine(q, pw) > embedding.cosine(q, pp)


def test_renumber_makes_citation_numbers_start_at_one_in_order_of_appearance():
    src = lambda n, t: {"n": n, "title": t, "item_id": f"i{n}", "kind_label": "x"}  # noqa: E731
    r = rag_chat.AskResult(
        answer="관리비 [11] 와 전기 [14] 그리고 수도 [3], 다시 관리비 [11]",
        source="ai",
        sources=[src(3, "수도"), src(11, "관리비"), src(14, "전기")],
    )
    rag_chat._renumber(r)
    assert r.answer == "관리비 [1] 와 전기 [2] 그리고 수도 [3], 다시 관리비 [1]"
    assert [(s["n"], s["title"]) for s in r.sources] == [(1, "관리비"), (2, "전기"), (3, "수도")]


def test_ask_renumbers_sources_after_several_searches(client, seeded):
    import json

    _, _, group = seeded
    steps = []

    def fake_post(body):
        steps.append(1)
        if len(steps) <= 2:  # 검색을 두 번 해서 ref 번호를 키운다
            call = {
                "type": "tool_use",
                "id": f"t{len(steps)}",
                "name": "search_knowledge",
                "input": {"query": "요금"},
            }
            return {"content": [call]}
        found = json.loads(body["messages"][-1]["content"][0]["content"])["results"]
        water = next(r["ref"] for r in found if r["title"] == "10월 수도요금")
        power = next(r["ref"] for r in found if r["title"] == "10월 전기요금")
        return {"content": [{"type": "text", "text": f"수도 [{water}], 전기 [{power}]"}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "요금 정리", post=fake_post)
    assert r.answer == "수도 [1], 전기 [2]"
    assert [(s["n"], s["title"]) for s in r.sources] == [(1, "10월 수도요금"), (2, "10월 전기요금")]


def test_demo_seed_has_receipts_for_expense_reports(client, family):
    from app.features.ai_assistant.knowledge.seed import seed_demo

    _, _, group = family
    with SessionLocal() as db:
        user_id = db.scalar(__import__("sqlalchemy").text("select id from users limit 1"))
        seed_demo(db, group["id"], user_id)
        kinds = ["마트 영수증", "쇼핑 영수증", "카페 영수증", "택시 영수증"]
        titles = [
            i["title"]
            for k in kinds
            for i in tools.list_items(db, group["id"], kind_label=k)["items"]
        ]
        assert len(titles) == 4
        top = tools.search_knowledge(db, group["id"], "영수증", top_k=20)["results"]
        assert sum("영수증" in r["kind_label"] for r in top) == 4


def _search_call(n):
    return {
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": f"t{n}",
                "name": "search_knowledge",
                "input": {"query": "고지서"},
            }
        ],
    }


def test_last_step_forbids_tools_so_the_answer_is_written(client, seeded):
    """도구를 세 번 쓰고 네 번째 호출에서는 도구를 못 쓰게 해 답을 받는다(예전에는 답이 비어 'AI 연결' 안내가 나갔다)."""
    _, _, group = seeded
    bodies = []

    def fake_post(body):
        bodies.append(body)
        if len(bodies) < rag_chat.MAX_STEPS:
            return _search_call(len(bodies))
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "찾은 근거예요."}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "수도요금", post=fake_post)
    assert len(bodies) == rag_chat.MAX_STEPS  # 호출 수는 그대로
    assert all("tool_choice" not in b for b in bodies[:-1])
    assert bodies[-1]["tool_choice"] == {"type": "none"} and bodies[-1]["tools"]
    last = bodies[-1]["messages"][-1][
        "content"
    ]  # 사고만 쓰고 끝나지 않게 마지막 user 메시지에 안내 한 줄
    assert last[-1] == {"type": "text", "text": LAST_CALL_NOTE} and last[0]["type"] == "tool_result"
    assert r.source == "ai" and r.answer == "찾은 근거예요."


def test_empty_answer_with_a_successful_call_is_not_called_an_ai_outage(client, seeded):
    _, _, group = seeded

    def thinking_only(body):
        return {"stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": ""}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "수도요금", post=thinking_only)
    assert r.source == "fallback" and "AI 연결" not in r.answer
    assert "답을 만들지 못했어요" in r.answer and r.sources


def test_plain_chat_leaves_room_for_thinking_and_answer(client, seeded):
    """웹 검색이 없는 일반 질문도 상한이 1024 면 사고가 다 쓰고 글 답이 없었다(q257)."""
    _, _, group = seeded
    bodies: list[dict] = []

    def fake_post(body):
        bodies.append(body)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "안녕하세요."}]}

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "안녕", post=fake_post)
    assert r.answer == "안녕하세요."
    assert (
        bodies[0]["max_tokens"] == settings.agent_max_output_tokens == 10000
    )  # 2026-11-25: 공통 설정(기존 2048)


def test_failed_ai_call_still_says_the_connection_is_off(client, seeded):
    import httpx

    _, _, group = seeded

    def broken(body):
        raise httpx.ConnectError("down")

    with SessionLocal() as db:
        r = rag_chat.ask(db, group["id"], "수도요금", post=broken)
    assert r.source == "fallback" and r.answer.startswith("AI 연결이 꺼져 있어서")


def _bodies_for(group_id, question, monkeypatch, *, score, web=False, model=None):
    """검색 최고 점수를 정해 두고 첫 호출이 도구를 부르게 한 뒤 보낸 요청 본문들을 모은다."""
    from types import SimpleNamespace

    real_search = service.search

    def search(
        *a, **k
    ):  # 첫 호출 전 한 건 확인(top_k=1)만 점수를 정해 두고, 도구의 검색은 그대로 둔다
        if k.get("top_k") == 1:
            return [SimpleNamespace(score=score)] if score else []
        return real_search(*a, **k)

    monkeypatch.setattr(rag_chat.service, "search", search)
    if model:
        monkeypatch.setattr(settings, "llm_model", model)
    if web:
        monkeypatch.setattr(settings, "web_search_enabled", True)
    bodies = []

    def fake_post(body):
        bodies.append(body)
        if len(bodies) == 1:
            return _search_call(1)
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "답이에요."}]}

    with SessionLocal() as db:
        rag_chat.ask(db, group_id, question, post=fake_post, web=web)
    return bodies


def test_first_call_forces_a_tool_when_documents_look_relevant(client, seeded, monkeypatch):
    _, _, group = seeded
    threshold = settings.chat_force_search_min_score
    bodies = _bodies_for(group["id"], "수도요금", monkeypatch, score=threshold)
    assert bodies[0]["tool_choice"] == {"type": "any"}
    assert "tool_choice" not in bodies[1]  # 두 번째 호출부터는 모델이 고른다


def test_first_call_is_not_forced_for_write_requests(client, seeded, monkeypatch):
    _, _, group = seeded
    threshold = settings.chat_force_search_min_score
    bodies = _bodies_for(group["id"], "수도요금 지출로 등록해줘", monkeypatch, score=threshold)
    assert "tool_choice" not in bodies[0]


def test_first_call_is_free_below_the_threshold_or_without_hits(client, seeded, monkeypatch):
    _, _, group = seeded
    below = settings.chat_force_search_min_score - 0.01
    assert "tool_choice" not in _bodies_for(group["id"], "안녕", monkeypatch, score=below)[0]
    assert "tool_choice" not in _bodies_for(group["id"], "안녕", monkeypatch, score=0)[0]


def test_force_can_be_turned_off(client, seeded, monkeypatch):
    _, _, group = seeded
    monkeypatch.setattr(settings, "chat_force_search_min_score", 0)
    assert "tool_choice" not in _bodies_for(group["id"], "수도요금", monkeypatch, score=0.99)[0]


def test_search_failure_does_not_block_the_question(client, seeded, monkeypatch):
    _, _, group = seeded

    def boom(*a, **k):
        raise RuntimeError("embedder down")

    monkeypatch.setattr(rag_chat.service, "search", boom)
    with SessionLocal() as db:
        assert rag_chat._documents_likely(db, group["id"], "수도요금") is False


def test_web_search_keeps_the_free_choice_and_uses_the_shared_token_limit(
    client, seeded, monkeypatch
):
    _, _, group = seeded
    bodies = _bodies_for(group["id"], "수도요금", monkeypatch, score=0.99, web=True)
    assert "tool_choice" not in bodies[0]
    assert bodies[0]["max_tokens"] == settings.agent_max_output_tokens == 10000  # 기존 웹 4096
    assert any(t.get("name") == "web_search" for t in bodies[0]["tools"])


def test_models_that_reject_forced_tool_use_are_not_forced(client, seeded, monkeypatch):
    _, _, group = seeded
    for model in ("claude-sonnet-5-5", "claude-opus-5-5"):
        bodies = _bodies_for(group["id"], "수도요금", monkeypatch, score=0.99, model=model)
        assert "tool_choice" not in bodies[0]


def test_ledger_empty_reply_is_not_returned_directly():
    """장부에 기록이 없다는 가계 답은 바로 돌려주지 않고 메인이 문서도 찾게 한다."""
    from app.features.ai_assistant.knowledge import rag_chat as rc

    assert rc.LEDGER_EMPTY.search("2025-05에는 정산 기록이 없어서 보낼 금액을 확인할 수 없어요.")
    assert rc.LEDGER_EMPTY.search("10월 지출 내역에는 칠순 비용이 없었어요.")
    assert not rc.LEDGER_EMPTY.search("10월 지출은 3건, 합계 52,000원이에요.")
