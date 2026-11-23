"""정산 에이전트의 지출 삭제 제안: 내가 낸 지출만, 정산하기 전만, 송금 완료 표시가 없는 달만. 앱 화면의 삭제보다 엄격하다.

삭제 대상은 사용자 문장이 제목·금액·날짜 중 하나로 가리킨 지출이어야 하고(`billing/target.py`), 모호한 요청('지난번에 낸 지출 지워 줘')에는
모델이 임의로 하나를 골라도 서버가 삭제 확인 카드를 만들지 않는다(T35 S2-B1 ambig-02)."""

import json

from app.shared.config import settings
from app.shared.llm import agent, proposals
from tests.ai_consent import enable_ai_for_user

from .test_billing_agent_write_stage1 import MONTH, _chat, _confirm, _owe_sujin_to_jimin

TOOL = "propose_delete_expense"


def _add(client, headers, title="치과", amount=50000, date="2026-10-12"):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": date},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _titles(client, headers):
    rows = client.get("/billing/expenses", params={"month": MONTH}, headers=headers).json()
    return sorted(e["title"] for e in rows)


def test_own_unsettled_expense_is_deleted_only_after_confirm(client, family, monkeypatch):
    a, _, _ = family
    eid = _add(client, a)
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid}, "치과 지출 지워 줘")
    assert out["tool_calls"] == [TOOL]
    (p,) = out["proposals"]
    assert p["summary"] == "지출 삭제: 치과 50,000원 (2026-10-12)"
    assert _titles(client, a) == ["치과"]  # 제안만으로는 지워지지 않는다
    assert _confirm(client, a, p["token"]).status_code == 200
    assert _titles(client, a) == []
    assert _confirm(client, a, p["token"]).status_code == 409  # 한 번만


def test_someone_elses_expense_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, b, "수진 간식", 3000)
    out = _chat(  # 지민이 수진의 지출을 지우려 함(문장이 그 지출을 가리켜도 내 지출이 아니면 거절)
        client, a, monkeypatch, TOOL, {"expense_id": eid}, "수진 간식 지워 줘"
    )
    assert out["proposals"] == []
    assert _titles(client, a) == ["수진 간식"]


def test_unknown_or_other_family_expense_is_not_proposed(client, family, other_family, monkeypatch):
    a, _, _ = family
    foreign = _add(client, other_family, "남의 가족 지출")
    for bad in ("nope", foreign, ""):
        out = _chat(client, a, monkeypatch, TOOL, {"expense_id": bad}, "남의 가족 지출 지워 줘")
        assert out["proposals"] == []
    assert _titles(client, other_family) == ["남의 가족 지출"]  # 다른 가족의 지출은 그대로다


def test_settled_expense_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a, "장보기", 10000)
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid}, "장보기 지워 줘")
    assert out["proposals"] == []
    assert _titles(client, a) == ["장보기"]


def test_month_with_a_completed_payment_is_locked_for_deletes(client, family, monkeypatch):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    spare = _add(client, a, "정산 전 지출", 1000)  # 정산하기를 하지 않은 내 지출
    t = client.get("/billing/settlement", params={"month": MONTH}, headers=a).json()["transfers"][0]
    client.post(
        "/billing/settlement/payments",
        json={
            "month": MONTH,
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": spare}, "정산 전 지출 지워 줘")
    assert out["proposals"] == []
    assert "정산 전 지출" in _titles(client, a)


def test_delete_is_rechecked_at_confirm_time(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a, "장보기", 10000)
    (p,) = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid}, "장보기 지워 줘")["proposals"]
    # 제안 뒤에 정산하기가 끝나면, 확인은 실패하고 지출은 남는다
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    r = _confirm(client, a, p["token"])
    assert r.status_code == 400 and r.json()["code"] == "expense_not_deletable"
    assert _titles(client, a) == ["장보기"]


def test_delete_token_cannot_be_used_by_another_member(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a)
    (p,) = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid}, "치과 지워 줘")["proposals"]
    assert _confirm(client, b, p["token"]).json()["code"] == "proposal_invalid"
    assert _titles(client, a) == ["치과"]


# ---- 모호한 삭제 요청: 모델이 임의로 지출을 골라도 서버가 삭제 확인 카드를 만들지 않는다 ----
def _chat_seeing_the_tool_result(client, headers, monkeypatch, args, message):
    """모델이 도구를 한 번 부르고, 두 번째 호출에서 본 대화(도구 결과 포함)를 함께 돌려준다."""
    seen: list[dict] = []

    def fake(body):
        if "가계(정산) 담당" not in body["system"]:
            return {"content": [{"type": "text", "text": "메인"}]}
        seen.append(body)
        if len(seen) == 1:
            return {"content": [{"type": "tool_use", "id": "t1", "name": TOOL, "input": args}]}
        return {"content": [{"type": "text", "text": "어느 지출인지 알려 주세요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    proposals.reset()
    r = client.post("/billing/agent/chat", json={"message": message}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), seen


def test_an_unidentified_request_creates_no_confirmation_even_if_the_model_picks_an_own_expense(
    client, family, monkeypatch
):
    a, _, _ = family
    chosen = _add(client, a, "수진이 학원비", 80000, "2026-10-05")
    _add(client, a, "문구류", 6000, "2026-10-07")
    for vague in ("지난번에 낸 지출 지워 줘", "그거 지워 줘", "내 지출 하나 지워 줘", "해줘"):
        out = _chat(client, a, monkeypatch, TOOL, {"expense_id": chosen}, vague)
        assert out["proposals"] == [], vague  # 삭제 확인 카드가 없다
    assert _titles(client, a) == ["문구류", "수진이 학원비"]  # 어떤 지출도 지워지지 않았다


def test_the_assistant_gets_an_error_that_tells_it_to_ask_which_expense(
    client, family, monkeypatch
):
    a, _, _ = family
    chosen = _add(client, a, "수진이 학원비", 80000, "2026-10-05")
    out, seen = _chat_seeing_the_tool_result(
        client, a, monkeypatch, {"expense_id": chosen}, "지난번에 낸 지출 지워 줘"
    )
    assert out["proposals"] == []
    result = json.dumps(seen[1]["messages"], ensure_ascii=False)
    assert '"is_error": true' in result.lower().replace('"is_error":true', '"is_error": true')
    assert "삭제 확인 카드를 만들지 말고" in result and "어느 지출" in result
    assert "수진이 학원비 80,000원" in result  # 되물을 때 보여 줄 후보도 함께 준다


def test_a_request_naming_another_expense_does_not_authorize_the_chosen_one(
    client, family, monkeypatch
):
    a, _, _ = family
    stationery = _add(client, a, "문구류", 6000, "2026-10-07")
    chosen = _add(client, a, "수진이 학원비", 80000, "2026-10-05")
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": chosen}, "문구류 지워 줘")
    assert out["proposals"] == []  # 문장은 문구류인데 모델이 학원비를 골랐다
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": stationery}, "문구류 지워 줘")
    (p,) = out["proposals"]
    assert p["summary"] == "지출 삭제: 문구류 6,000원 (2026-10-07)"
    assert _titles(client, a) == ["문구류", "수진이 학원비"]


def test_a_clear_request_by_title_amount_or_date_keeps_the_normal_approval_flow(
    client, family, monkeypatch
):
    a, _, _ = family
    school = _add(client, a, "수진이 학원비", 80000, "2026-10-05")
    pens = _add(client, a, "문구류", 6000, "2026-10-07")
    for expense_id, message in (
        (school, "수진이 학원비 지워 줘"),
        (school, "10월 5일에 쓴 지출 지워 줘"),
        (pens, "6,000원 지출 지워 줘"),
        (pens, "2026-10-07 지출 삭제해 줘"),
    ):
        out = _chat(client, a, monkeypatch, TOOL, {"expense_id": expense_id}, message)
        assert len(out["proposals"]) == 1, message
    assert _titles(client, a) == ["문구류", "수진이 학원비"]  # 확인 전에는 지워지지 않는다
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": pens}, "문구류 지워 줘")
    (p,) = out["proposals"]
    assert _confirm(client, a, p["token"]).status_code == 200
    assert _titles(client, a) == ["수진이 학원비"]


def test_a_title_shared_by_two_expenses_needs_one_more_detail(client, family, monkeypatch):
    a, _, _ = family
    first = _add(client, a, "장보기", 30000, "2026-10-08")
    second = _add(client, a, "장보기", 45000, "2026-10-12")
    for expense_id in (first, second):
        out = _chat(client, a, monkeypatch, TOOL, {"expense_id": expense_id}, "장보기 지워 줘")
        assert out["proposals"] == []
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": second}, "장보기 45,000원 지워 줘")
    (p,) = out["proposals"]
    assert p["summary"] == "지출 삭제: 장보기 45,000원 (2026-10-12)"
    assert _titles(client, a) == ["장보기", "장보기"]


def test_another_familys_expense_is_still_isolated_even_when_the_message_names_it(
    client, family, other_family, monkeypatch
):
    a, _, _ = family
    foreign = _add(client, other_family, "남의 가족 지출", 77777)
    out = _chat(
        client, a, monkeypatch, TOOL, {"expense_id": foreign}, "남의 가족 지출 77,777원 지워 줘"
    )
    assert out["proposals"] == []
    assert _titles(client, other_family) == ["남의 가족 지출"]
