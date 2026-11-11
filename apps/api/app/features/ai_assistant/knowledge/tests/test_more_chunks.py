"""검색 결과의 기록당 조각 여러 개, get_item 상한, 읽어 보고 답하라는 지시, 채팅 에이전트 직통 응답 예외."""

import pytest

from app.features.ai_assistant.knowledge import rag_chat, service, tools
from app.shared.config import settings
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

MANUAL = "# 세탁기 사용 설명서\n분류: 설명서\n" + "\n".join(
    f"[p.{n}]\n{n}쪽 항목: {word} 관련 안내 문장입니다. " + "설명이 이어집니다. " * 8
    for n, word in enumerate(["전원", "세탁 코스", "배수 필터 청소", "오류 코드", "보증 기간"], 1)
)
SMALL = "# 수도요금\n분류: 수도요금 고지서\n- 사용량 18톤"


def _add(client, headers, **kw):
    r = client.post("/ai-assistant/knowledge/items", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _manual(client, headers):
    return _add(client, headers, kind_label="설명서", title="세탁기 설명서", body_md=MANUAL)


def test_search_returns_one_chunk_per_record_by_default(client, family):
    a, _, group = family
    _manual(client, a)
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수 필터 청소 방법", top_k=3)
        assert len(hits) == 1 and hits[0].more == ()  # 다른 호출자(lookup, 라우터) 동작 유지


def test_search_can_return_several_chunks_of_one_record(client, family):
    a, _, group = family
    item = _manual(client, a)
    with SessionLocal() as db:
        hits = service.search(db, group["id"], "배수 필터 청소 방법", top_k=3, per_item=3)
        assert len(hits) == 1 and len(hits[0].more) == 2 and hits[0].item.id == item["id"]
        pages = [hits[0].chunk.page_label] + [c.page_label for c in hits[0].more]
        assert len(set(pages)) == 3


def test_search_knowledge_adds_more_chunks_within_the_limits(client, family, monkeypatch):
    a, _, group = family
    _manual(client, a)
    with SessionLocal() as db:
        found = tools.search_knowledge(db, group["id"], "배수 필터 청소 방법")
        assert len(found["results"]) == 1  # 기록 수는 그대로(출처는 기록 단위)
        row = found["results"][0]
        assert row["page"] and 1 <= len(row["more"]) <= tools.EXTRA_CHUNKS_PER_ITEM
        assert all(m["page"] and m["text"] for m in row["more"])
        assert sum(len(m["text"]) for m in row["more"]) <= tools.EXTRA_CHARS
        assert "get_item" in found["note"]
        monkeypatch.setattr(tools, "EXTRA_CHARS", 10)  # 합계 상한보다 큰 조각은 싣지 않는다
        assert (
            "more"
            not in tools.search_knowledge(db, group["id"], "배수 필터 청소 방법")["results"][0]
        )


def test_source_chip_keeps_the_page_of_the_best_chunk(client, family):
    a, _, group = family
    _manual(client, a)
    with SessionLocal() as db:
        row = tools.search_knowledge(db, group["id"], "배수 필터 청소 방법")["results"][0]
    source = rag_chat._source({**row, "ref": 1}, 1)
    assert source["page"] == row["page"] and source["item_id"] == row["item_id"]


def test_get_item_cuts_a_huge_record_and_says_so(client, family):
    a, _, group = family
    big = "# 큰 문서\n분류: 계약서\n" + "조항 내용 줄입니다.\n" * 6000
    item = _add(client, a, kind_label="계약서", title="큰 문서", body_md=big)
    small = _add(client, a, kind_label="수도요금 고지서", title="수도요금", body_md=SMALL)
    with SessionLocal() as db:
        out = tools.get_item(db, group["id"], item["id"])
        assert len(out["text"]) == tools.GET_ITEM_MAX_CHARS
        assert str(len(big)) in out["note"] and "search_knowledge" in out["note"]
        assert "note" not in tools.get_item(db, group["id"], small["id"])


def test_prompt_tells_to_read_the_record_before_giving_up():
    prompt = rag_chat.SYSTEM_PROMPT
    assert "get_item" in prompt and prompt.index("get_item") < prompt.index("찾지 못했다고")


def _direct_ready(question: str, agent: str = "ask_family_chat") -> bool:
    result = rag_chat.AskResult("", "ai")
    result.tool_calls.append({"name": agent})
    data = {"answer": "11월 14일에 외할머니 댁에서 모이기로 했어요", "can_answer": True}
    return rag_chat._direct_reply_ready(
        [{"name": agent}], result, (agent, data, []), False, question
    )


def test_chat_agent_answer_is_not_final_when_the_user_asked_to_write(monkeypatch):
    monkeypatch.setattr(settings, "assistant_direct_agent_reply", True)
    assert _direct_ready("채팅에서 정한 외할머니 댁 모임 언제야?") is True  # 조회만이면 직통 유지
    assert _direct_ready("채팅에서 정한 외할머니 댁 모임, 일정에 넣어줘") is False
    assert _direct_ready("채팅에서 정한 외할머니 댁 모임, 일정에 넣어줘", "ask_billing") is True


def test_main_prompt_keeps_edit_and_delete_words_for_the_schedule_agent():
    from app.features.ai_assistant import agents

    note = agents.PROMPT_NOTE
    assert "지워줘" in note and "조회 문장으로 바꾸지 마세요" in note
