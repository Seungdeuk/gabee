"""제목으로 대상을 가리킨 지출 삭제 요청은 메인을 거쳐 정산 Agent 의 삭제 '제안'(확인 카드)까지 그대로 간다(앱 API·가짜 LLM, 실제 호출 없음).

E8 ambig-02 의 메인 프롬프트 지침(대상이 정해지지 않았을 때만 먼저 되묻는다)이 명확한 요청의 기존 흐름을 막지 않는지 확인한다. 가짜 모델은 프롬프트를 따르지 않으므로
'실제 모델이 명확한 요청까지 되묻는지(과잉 되묻기)'는 이 시험으로 알 수 없고 실모델로만 본다. 여기서는 ① 메인이 받는 시스템 프롬프트에 '가리킨 요청은 그대로 넘긴다'는
문장이 함께 있고 ② 가짜 모델이 그대로 넘겼을 때 서버가 확인 카드만 만들고(삭제는 확인 뒤에만) ③ 모호한 요청은 서버 가드가 여전히 막는지(`billing/target.py`)를 본다.
"""

import json

from sqlalchemy import select

from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing.models import Expense
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.ai_consent import enable_ai

CLEAR = "제목·금액·날짜 중 하나로 가리킨 요청은 지금처럼 그대로 ask_billing 으로 넘기세요"
ASK_FIRST = "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요"


def _tool_use(name, args):
    return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _add(client, headers, title="치과", amount=50000, date="2026-10-12"):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": date},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _titles():
    with SessionLocal() as db:
        return sorted(db.scalars(select(Expense.title)).all())


def _run(client, headers, monkeypatch, message, expense_id, forwarded):
    seen = {"main_system": [], "billing_tools": []}

    def fake_post(body):
        if "가계(정산) 담당" in body["system"]:
            if len(body["messages"]) == 1:
                seen["billing_tools"].append("propose_delete_expense")
                return _tool_use("propose_delete_expense", {"expense_id": expense_id})
            return _text("삭제를 제안했어요. 화면의 확인 버튼을 눌러야 삭제돼요.")
        seen["main_system"].append(body["system"])
        if len(body["messages"]) == 1:
            return _tool_use("ask_billing", {"question": forwarded})
        return _text("확인 카드의 버튼을 눌러야 삭제돼요.")

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": message}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), seen


def test_a_title_named_delete_request_reaches_billing_and_only_a_proposal_is_made(
    client, family, monkeypatch
):
    a, _, group = family
    enable_ai(group["id"])
    eid = _add(client, a)
    out, seen = _run(client, a, monkeypatch, "치과 지출 지워 줘", eid, "치과 지출을 지워 줘")
    assert seen["billing_tools"] == ["propose_delete_expense"]  # 메인이 정산 Agent 로 넘겼다
    system = seen["main_system"][0]
    assert CLEAR in system and ASK_FIRST in system  # 새 지침과 '명확한 요청은 그대로'가 함께 간다
    assert system.count(ASK_FIRST) == 1
    proposals = out.get("proposals") or out.get("pending_confirmations") or []
    assert len(proposals) == 1, json.dumps(out, ensure_ascii=False)[:400]
    assert _titles() == ["치과"]  # 제안만으로는 지워지지 않는다


def test_a_vague_request_forwarded_with_a_guess_is_still_refused_by_the_server_guard(
    client, family, monkeypatch
):
    """모호한 요청('그거 지워 줘')을 메인이 최근 지출로 추정해 넘겨도 서버 가드(`billing/target.py`)가 삭제 확인 카드를 만들지 않는다."""
    a, _, group = family
    enable_ai(group["id"])
    eid = _add(client, a, "학원비", 80000, "2026-11-05")
    out, _ = _run(
        client,
        a,
        monkeypatch,
        "그거 지워 줘",
        eid,
        "가장 최근에 등록한 지출을 찾아서 삭제 확인을 요청해 주세요",
    )
    proposals = out.get("proposals") or out.get("pending_confirmations") or []
    assert proposals == []
    assert _titles() == ["학원비"]


def test_without_the_server_guard_the_vague_forward_would_make_a_card(client, family, monkeypatch):
    """대조: 서버 가드를 끄면 같은 모호한 전달이 삭제 확인 카드를 만든다(위 시험이 가드 덕에 통과함을 확인한다)."""
    from app.features.billing import agent as billing_agent

    a, _, group = family
    enable_ai(group["id"])
    eid = _add(client, a, "학원비", 80000, "2026-11-05")
    monkeypatch.setattr(billing_agent.target, "ensure_identified", lambda *args, **kwargs: None)
    out, _ = _run(
        client,
        a,
        monkeypatch,
        "그거 지워 줘",
        eid,
        "가장 최근에 등록한 지출을 찾아서 삭제 확인을 요청해 주세요",
    )
    proposals = out.get("proposals") or out.get("pending_confirmations") or []
    assert len(proposals) == 1
    assert _titles() == ["학원비"]  # 카드만 만들어지고 삭제는 확인 뒤에만
