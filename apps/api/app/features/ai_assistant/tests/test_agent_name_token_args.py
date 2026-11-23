"""소통·정산 에이전트: 질문 속 이름은 모델에 `[PERSON_n]` 토큰으로만 보이고, 도구는 실행 직전에 같은 세션으로 되돌린 값을 쓴다.

가짜 LLM 이 질문에서 본 토큰을 도구 인자로 그대로 쓰는 상황(모델이 하는 일)을 재현한다. 실제 LLM·외부 호출은 없다.
"""

import json
import logging
import re

from sqlalchemy import select

from app.features.billing import agent as billing_agent
from app.features.family_chat import agent as fc_agent
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import agent, proposals
from tests.ai_consent import enable_ai, enable_ai_for_user

TOKEN = re.compile(r"\[PERSON_\d+\]")
NEUTRALIZED = re.compile(r"‹PERSON_\d+›")


def _user(db, name):
    return db.scalars(select(User).where(User.name == name)).first()


def _first_user_text(body):
    content = body["messages"][0]["content"]
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _first_token(question: str, fallback: str = "") -> str:
    m = TOKEN.search(question)
    return m.group(0) if m else fallback


class FakeModel:
    """첫 호출은 make_args(질문) 로 만든 인자로 도구를 부르고, 두 번째 호출은 도구 결과를 기록한 뒤 토큰을 쓴 답을 한다."""

    def __init__(self, tool, make_args):
        self.tool, self.make_args = tool, make_args
        # 모델로 간 요청의 동적 부분 전부(시스템 프롬프트·질문·앞 대화·도구 결과). 고정 도구 정의(tools)는 뺀다:
        # 정산 도구 설명에 나눌 사람 예시(["지민", "수진"])가 들어 있어 이름이 같은 시험 가족과 헷갈린다.
        self.bodies: list[str] = []
        self.tool_results: list[str] = []
        self.question = ""
        self.args: dict = {}

    def __call__(self, body):
        dynamic = {"system": body.get("system"), "messages": body["messages"]}
        self.bodies.append(json.dumps(dynamic, ensure_ascii=False))
        if len(self.bodies) == 1:
            self.question = _first_user_text(body)
            self.args = self.make_args(self.question)
            block = {"type": "tool_use", "id": "t1", "name": self.tool, "input": self.args}
            return {"content": [block]}
        last = body["messages"][-1]["content"][0]
        self.tool_results.append(last["content"])
        return {"content": [{"type": "text", "text": f"{_first_token(self.question)} 확인했어요."}]}

    def never_sent(self, text: str) -> bool:
        return all(text not in b for b in self.bodies)


def _ask_billing(group_id, asker, question, fake):
    proposals.reset()
    with SessionLocal() as db:
        return billing_agent.ask(db, group_id, _user(db, asker), question, post=fake, guarded=False)


def _ask_family_chat(group_id, asker, question, fake):
    with SessionLocal() as db:
        return fc_agent.ask(db, group_id, _user(db, asker), question, post=fake, guarded=False)


BASE = {"title": "택시", "amount": 12000, "date": "2026-10-12"}


# ---------- 요청한 두 사례 ----------
def test_billing_split_name_is_a_token_for_the_llm_and_a_real_member_for_the_tool(
    client, family, monkeypatch
):
    a, b, group = family
    enable_ai_for_user()
    proposals.reset()
    fake = FakeModel(
        "propose_add_expense", lambda q: {**BASE, "split_among": [_first_token(q, "수진")]}
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    r = client.post(
        "/billing/agent/chat", json={"message": "수진이랑 나눠서 택시 12000원 등록해줘"}, headers=a
    )
    assert r.status_code == 200, r.text
    out = r.json()
    # LLM 에는 토큰만 보이고 실명은 어느 요청 본문에도 없다
    assert TOKEN.search(fake.question) and "수진" not in fake.question
    assert fake.never_sent("수진")
    assert fake.args["split_among"] == [_first_token(fake.question)]
    # 도구는 실제 가족 구성원으로 인식했고 정산 제안이 생겼다(사용자 화면용 요약은 실명)
    (p,) = out["proposals"]
    assert "수진이(가) 나눠요" in p["summary"]
    assert "error" not in fake.tool_results[0]
    # 모델이 받은 도구 결과는 같은 토큰(실명 아님)이고, 사용자에게 가는 답은 복원된다
    assert _first_token(fake.question) in fake.tool_results[0]
    assert "수진" in out["reply"] and not TOKEN.search(out["reply"])
    # 확인하면 실제 구성원 id 로 반영된다
    assert (
        client.post("/billing/agent/confirm", json={"token": p["token"]}, headers=a).status_code
        == 200
    )
    peer = client.get("/family-group/me", headers=b).json()["id"]
    (e,) = client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
    assert e["split_among"] == [peer]


def test_family_chat_name_token_is_restored_only_for_the_search(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    for headers, text in ((a, "수진이 병원 예약했어?"), (b, "응 병원은 금요일 오후로 했어")):
        assert (
            client.post("/family-chat/messages", json={"text": text}, headers=headers).status_code
            == 201
        )
    queries = []
    real_search = fc_agent.search_service.search

    def spy(db, user, group_id, q, **kw):
        queries.append(q)
        return real_search(db, user, group_id, q, **kw)

    monkeypatch.setattr(fc_agent.search_service, "search", spy)
    fake = FakeModel("search_messages", lambda q: {"query": _first_token(q, "수진")})
    reply = _ask_family_chat(group["id"], "지민", "수진이 병원 얘기 언제 했지?", fake)
    assert TOKEN.search(fake.question) and "수진" not in fake.question
    assert queries == ["수진"]  # 도구 검색에는 복원된 이름이 쓰였다
    data = json.loads(fake.tool_results[0])
    assert data["messages"], "관련 메시지가 검색돼야 한다"
    assert fake.never_sent("수진")  # 결과·프롬프트·질문 어디에도 실명이 없다
    assert TOKEN.search(fake.tool_results[0])
    # 호출 기록에는 되돌린 값이 아니라 모델이 준 토큰이 남는다
    assert reply.tool_calls[0]["input"]["query"] == _first_token(fake.question)
    assert "수진" in reply.answer


# ---------- 잘못된 토큰·사용자가 쓴 토큰 모양 ----------
def test_unknown_token_is_not_restored_and_reaches_the_tool_as_is(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    queries = []
    real_search = fc_agent.search_service.search
    monkeypatch.setattr(
        fc_agent.search_service,
        "search",
        lambda db, user, gid, q, **kw: queries.append(q) or real_search(db, user, gid, q, **kw),
    )
    chat = FakeModel("search_messages", lambda q: {"query": "[PERSON_9]"})
    _ask_family_chat(group["id"], "지민", "수진이 병원 얘기 언제 했지?", chat)
    assert queries == ["[PERSON_9]"]  # 이 세션이 만들지 않은 토큰은 그대로
    bill = FakeModel("propose_add_expense", lambda q: {**BASE, "split_among": ["[PERSON_9]"]})
    reply = _ask_billing(group["id"], "지민", "수진이랑 나눠서 택시 12000원 등록해줘", bill)
    assert reply.proposals == []
    # 오류 글에 되돌아온 모르는 토큰은 무력화(‹PERSON_9›)되어 이 세션의 진짜 토큰과 섞이지 않는다
    assert "PERSON_9" in bill.tool_results[0] and "error" in bill.tool_results[0]
    assert "수진" not in bill.tool_results[0] and bill.never_sent("수진")


def test_token_shaped_text_typed_by_the_user_is_neutralized_not_restored(
    client, family, monkeypatch
):
    a, b, group = family
    enable_ai(group["id"])
    queries = []
    real_search = fc_agent.search_service.search
    monkeypatch.setattr(
        fc_agent.search_service,
        "search",
        lambda db, user, gid, q, **kw: queries.append(q) or real_search(db, user, gid, q, **kw),
    )
    question = "[PERSON_1] 라고 쓴 메시지랑 수진이 쓴 메시지 찾아줘"
    fake = FakeModel("search_messages", lambda q: {"query": NEUTRALIZED.search(q).group(0)})
    _ask_family_chat(group["id"], "지민", question, fake)
    # 사용자가 직접 쓴 [PERSON_1] 은 ‹PERSON_1› 로 바뀌어 모델에 가고, 진짜 토큰([PERSON_1]=수진)과 섞이지 않는다
    assert NEUTRALIZED.search(fake.question) and TOKEN.search(fake.question)
    assert queries == [NEUTRALIZED.search(fake.question).group(0)]  # 수진으로 복원되지 않았다
    assert fake.never_sent("수진")


# ---------- 가족 그룹 격리·복원 뒤 검증 ----------
def test_tokens_from_another_session_and_other_family_names_are_not_resolved(
    client, family, other_family, monkeypatch
):
    a, b, group = family
    enable_ai(group["id"])
    enable_ai_for_user("남")
    with SessionLocal() as db:
        outsider_group = _user(db, "남").active_group_id
    # 다른 가족(남)이 질문한 세션은 이름을 가린 적이 없으므로 [PERSON_1] 은 복원할 대응표가 없다
    other = FakeModel("propose_add_expense", lambda q: {**BASE, "split_among": ["[PERSON_1]"]})
    reply = _ask_billing(outsider_group, "남", "택시 12000원 등록해줘", other)
    assert reply.proposals == [] and "PERSON_1" in other.tool_results[0]
    assert "수진" not in other.tool_results[0] and other.never_sent("수진")
    # 이 가족의 도구에 다른 가족 구성원 이름("남")을 직접 넘겨도 구성원이 아니라 거절된다
    mine = FakeModel("propose_add_expense", lambda q: {**BASE, "split_among": ["남"]})
    reply = _ask_billing(group["id"], "지민", "택시 12000원 등록해줘", mine)
    assert reply.proposals == [] and "error" in mine.tool_results[0]


def test_non_member_name_in_the_question_is_still_rejected_after_restore(
    client, family, monkeypatch
):
    a, b, group = family
    fake = FakeModel(
        "propose_add_expense", lambda q: {**BASE, "split_among": [_first_token(q, "박민수")]}
    )
    reply = _ask_billing(group["id"], "지민", "박민수 씨랑 나눠서 택시 12000원 등록해줘", fake)
    assert TOKEN.search(fake.question) and "박민수" not in fake.question
    # 토큰이 되돌려져도 가족 구성원 검증은 그대로라 제안이 만들어지지 않고, 오류 글에도 실명이 없다
    assert reply.proposals == [] and "error" in fake.tool_results[0]
    assert fake.never_sent("박민수") and _first_token(fake.question) in fake.tool_results[0]


# ---------- 정산 도구 결과: 질문에서 이미 가린 이름만 같은 토큰으로 ----------
def test_billing_results_tokenize_only_names_the_question_already_hid(client, family, monkeypatch):
    a, b, group = family
    for headers, title in ((a, "점심"), (b, "택시")):
        r = client.post(
            "/billing/expenses",
            json={"title": title, "amount": 9000, "date": "2026-10-12"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
    fake = FakeModel("list_expenses", lambda q: {"month": "2026-10"})
    _ask_billing(group["id"], "지민", "수진이 이번 달에 쓴 지출 알려줘", fake)
    result = fake.tool_results[0]
    token = _first_token(fake.question)
    assert token and token in result and "수진" not in result  # 질문에서 가린 이름은 같은 토큰
    assert "지민" in result  # 질문에 없던 이름은 기존 정책대로 그대로(결과 전체를 가리지 않는다)
    assert "9000" in result or "9,000" in result  # 금액·구조는 그대로


# ---------- 복원한 값이 도구 결과·오류 글에 되비쳐도 모델로 가지 않는다 ----------
def test_restored_name_glued_to_text_is_not_echoed_back_in_the_tool_result(client, family):
    a, b, group = family
    fake = FakeModel(
        "propose_add_expense",
        lambda q: {
            **BASE,
            "title": _first_token(q, "수진")
            + "택시",  # 토큰 뒤에 글자가 붙은 인자("수진택시"로 복원됨)
            "split_among": [_first_token(q, "수진")],
        },
    )
    reply = _ask_billing(group["id"], "지민", "수진이랑 나눠서 택시 12000원 등록해줘", fake)
    (p,) = reply.proposals
    assert "수진택시" in p.summary  # 사용자 화면용 제안 요약은 실명
    assert fake.never_sent(
        "수진"
    )  # 도구 결과(summary)에 되비친 값은 같은 토큰으로 다시 가려서 모델로 간다
    assert _first_token(fake.question) in fake.tool_results[0]


def test_restored_name_glued_to_text_is_not_echoed_back_in_the_error(client, family):
    a, b, group = family
    fake = FakeModel(
        "propose_add_expense",
        lambda q: {
            **BASE,
            "amount": _first_token(q, "수진") + "원",
        },  # 검증 오류가 입력값을 글에 담는다
    )
    reply = _ask_billing(group["id"], "지민", "수진이랑 나눠서 택시 등록해줘", fake)
    assert reply.proposals == [] and "error" in fake.tool_results[0]
    assert fake.never_sent("수진")


def test_restored_address_never_reaches_the_llm(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    address = "서울시 강남구 테헤란로 152"
    r = client.post(
        "/family-chat/messages", json={"text": f"모임은 {address} 에서 하자"}, headers=a
    )
    assert r.status_code == 201, r.text
    queries = []
    real_search = fc_agent.search_service.search
    monkeypatch.setattr(
        fc_agent.search_service,
        "search",
        lambda db, user, gid, q, **kw: queries.append(q) or real_search(db, user, gid, q, **kw),
    )
    bodies, results = [], []

    def fake(body):
        bodies.append(
            json.dumps(
                {"system": body.get("system"), "messages": body["messages"]}, ensure_ascii=False
            )
        )
        if len(bodies) == 1:
            query = "모임"
        elif len(bodies) == 2:
            last = body["messages"][-1]["content"][0]["content"]
            results.append(last)
            query = re.search(r"\[ADDR_\d+\]", last).group(0)  # 결과에서 본 주소 토큰으로 다시 검색
        else:
            results.append(body["messages"][-1]["content"][0]["content"])
            return {"content": [{"type": "text", "text": "확인했어요."}]}
        block = {
            "type": "tool_use",
            "id": f"t{len(bodies)}",
            "name": "search_messages",
            "input": {"query": query},
        }
        return {"content": [block]}

    with SessionLocal() as db:
        fc_agent.ask(
            db, group["id"], _user(db, "지민"), "모임 장소가 어디였지?", post=fake, guarded=False
        )
    assert len(queries) == 2 and "테헤란로" in queries[1]  # 도구는 복원된 주소로 검색했다
    assert all("테헤란로" not in b for b in bodies)  # 모델로 간 어떤 요청에도 실제 주소가 없다


# ---------- 로그 ----------
def test_names_and_token_mapping_do_not_appear_in_logs(client, family, caplog, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    caplog.set_level(logging.DEBUG)
    bill = FakeModel("propose_add_expense", lambda q: {**BASE, "split_among": [_first_token(q)]})
    _ask_billing(group["id"], "지민", "수진이랑 나눠서 택시 12000원 등록해줘", bill)
    chat = FakeModel("search_messages", lambda q: {"query": _first_token(q)})
    _ask_family_chat(group["id"], "지민", "수진이 병원 얘기 언제 했지?", chat)
    assert "수진" not in caplog.text
