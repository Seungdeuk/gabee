"""가족 채팅방에서 @가비 로 부른 답은 항상 방에 공유된다(visibility=room). 개인 대화는 항상 private. 실제 LLM 은 부르지 않는다."""

import json

from app.features.ai_assistant.knowledge import rag_chat
from app.features.ai_assistant.knowledge import service as kservice
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


# ---------- 채팅 요청 ----------
def _fake(monkeypatch, main_tool, main_args, sub_tool=None, sub_args=None):
    def fake_post(body):
        sub = "가계(정산) 담당" in body["system"] or "돌봄 담당" in body["system"]
        if sub:
            if len(body["messages"]) == 1:
                return _tool_use(sub_tool, sub_args or {})
            return _text("확인했어요.")
        if len(body["messages"]) == 1:
            return _tool_use(main_tool, main_args)
        last = body["messages"][-1]["content"][0]["content"]
        data = json.loads(last)
        return _text(data.get("answer") or "찾아봤어요.")

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)


def _chat(client, headers, audience=None):
    body = {"message": "질문"}
    if audience:
        body["audience"] = audience
    r = client.post("/ai-assistant/chat", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_personal_chat_is_always_private(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    _fake(monkeypatch, "ask_billing", {"question": "이번 달 지출"}, "get_month_summary", {})
    out = _chat(client, a)  # audience 를 안 보내면 개인 대화
    assert out["visibility"] == "private" and out["private_reasons"] == []


def test_room_billing_summary_is_shareable(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    _fake(monkeypatch, "ask_billing", {"question": "이번 달 지출"}, "get_month_summary", {})
    out = _chat(client, a, "room")
    assert out["visibility"] == "room" and out["private_reasons"] == []


def test_room_allowance_question_is_shared(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    _fake(monkeypatch, "ask_billing", {"question": "용돈 잔액"}, "list_allowances", {})
    out = _chat(client, a, "room")
    assert out["visibility"] == "room" and out["private_reasons"] == []


def test_room_sensitive_record_is_shared(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    with SessionLocal() as db:
        owner = client.get("/family-group/me", headers=a).json()["id"]
        kservice.ingest(
            db,
            group["id"],
            owner,
            kind_label="처방전",
            title="혈압약 처방전",
            body_md="# 혈압약 처방전\n분류: 처방전\n혈압약 30일치",
            sensitivity="sensitive",
        )
    _fake(monkeypatch, "search_knowledge", {"query": "혈압약 처방전"})
    out = _chat(client, a, "room")
    assert out["visibility"] == "room" and out["private_reasons"] == []


def test_room_ordinary_record_is_shareable(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    with SessionLocal() as db:
        owner = client.get("/family-group/me", headers=a).json()["id"]
        kservice.ingest(
            db,
            group["id"],
            owner,
            kind_label="전기요금 고지서",
            title="9월 전기요금",
            body_md="# 9월 전기요금\n분류: 전기요금 고지서\n청구금액 61,240원",
        )
    _fake(monkeypatch, "search_knowledge", {"query": "전기요금"})
    out = _chat(client, a, "room")
    assert out["visibility"] == "room"


def test_room_without_ai_answer_is_shared_too(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "")  # AI 를 못 써서 기본 안내가 나온다
    out = _chat(client, a, "room")
    assert out["source"] == "fallback" and out["visibility"] == "room"


def test_room_sensitive_record_found_but_not_used_is_shareable(client, family, monkeypatch):
    """검색에 민감 기록이 섞여도 답이 그 기록을 쓰지 않았으면 방에 올릴 수 있다(병원·보험 기록이 많은 가족도 쓸 수 있게)."""
    a, _, group = family
    enable_ai(group["id"])
    with SessionLocal() as db:
        owner = client.get("/family-group/me", headers=a).json()["id"]
        kservice.ingest(
            db,
            group["id"],
            owner,
            kind_label="전기요금 고지서",
            title="9월 전기요금",
            body_md="# 9월 전기요금\n분류: 전기요금 고지서\n청구금액 61,240원 처방전",
        )
        kservice.ingest(
            db,
            group["id"],
            owner,
            kind_label="처방전",
            title="혈압약 처방전",
            body_md="# 혈압약 처방전\n분류: 처방전\n전기요금 처방전 혈압약",
            sensitivity="sensitive",
        )

    def fake_post(body):
        if len(body["messages"]) == 1:
            return _tool_use("search_knowledge", {"query": "전기요금 처방전", "top_k": 5})
        data = json.loads(body["messages"][-1]["content"][0]["content"])
        titles = {r["title"]: r["ref"] for r in data["results"]}
        assert "혈압약 처방전" in titles and "9월 전기요금" in titles  # 둘 다 검색에 걸렸다
        return _text(f"9월 전기요금은 61,240원이에요 [{titles['9월 전기요금']}].")

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    out = _chat(client, a, "room")
    assert out["visibility"] == "room" and [s["title"] for s in out["sources"]] == ["9월 전기요금"]


def test_audience_must_be_known(client, family):
    a, _, _ = family
    r = client.post("/ai-assistant/chat", json={"message": "x", "audience": "everyone"}, headers=a)
    assert r.status_code == 422
