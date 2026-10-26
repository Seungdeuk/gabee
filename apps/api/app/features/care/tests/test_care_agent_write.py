"""돌봄 에이전트의 쓰기: 식단·항목 기록도 제안만 하고, 확인(agent/confirm)해야 실행된다."""

from app.shared.config import settings
from app.shared.llm import agent, proposals
from tests.ai_consent import enable_ai_for_user


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _llm(name, args):
    calls = []

    def fake(body):
        calls.append(1)
        if len(calls) == 1:
            return _tool_use(name, args)
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    return fake


def _setup(monkeypatch, fake):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    proposals.reset()


def _meals(client, headers):
    params = {"days": 1, "end": "2026-10-20"}
    days = client.get("/care/meal-log", params=params, headers=headers).json()["days"]
    return [(s["meal"], s["log"]["menu"]) for d in days for s in d["slots"] if s["log"]]


def _post(client, headers, path, body):
    return client.post(path, json=body, headers=headers)


def test_meal_proposal_is_written_only_after_confirm(client, family, monkeypatch):
    a, b, _ = family
    args = {"meal": "lunch", "menu": "비빔밥", "date": "2026-10-20"}
    _setup(monkeypatch, _llm("propose_record_meal", args))
    r = _post(client, a, "/care/agent/chat", {"message": "점심 비빔밥 기록해줘"}).json()
    (p,) = r["proposals"]
    assert p["tab"] == "care" and "점심 비빔밥" in p["summary"]
    assert _meals(client, a) == []
    assert _post(client, b, "/care/agent/confirm", {"token": p["token"]}).status_code == 400
    assert _post(client, a, "/care/agent/confirm", {"token": p["token"]}).status_code == 200
    assert _meals(client, a) == [("lunch", "비빔밥")]


def test_item_proposal_validates_item_and_value(client, family, monkeypatch):
    a, _, _ = family
    daily = client.get("/care/daily", params={"date": "2026-10-20"}, headers=a).json()
    yesno = next(i for i in daily["items"] if i["mode"] == "yesno")
    chat = {"message": "기록"}
    _setup(monkeypatch, _llm("propose_record_item", {"item_id": "없는-항목", "done": True}))
    assert _post(client, a, "/care/agent/chat", chat).json()["proposals"] == []
    _setup(monkeypatch, _llm("propose_record_item", {"item_id": yesno["id"]}))  # 값이 없다
    assert _post(client, a, "/care/agent/chat", chat).json()["proposals"] == []
    ok = {"item_id": yesno["id"], "done": True, "date": "2026-10-20"}
    _setup(monkeypatch, _llm("propose_record_item", ok))
    (p,) = _post(client, a, "/care/agent/chat", chat).json()["proposals"]
    assert yesno["name"] in p["summary"] and "완료" in p["summary"]
    assert _post(client, a, "/care/agent/confirm", {"token": p["token"]}).status_code == 200
    after = client.get("/care/daily", params={"date": "2026-10-20"}, headers=a).json()
    assert next(i for i in after["items"] if i["id"] == yesno["id"])["completed"] is True
