"""메인 채팅의 일정 공유 등록·수정·삭제는 실행하지 않고 확인 카드(confirm_cards)로 돌려주고, 앱이 버튼으로 `/schedule/agent/confirm` 을 눌러 실행한다."""

import json

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.features.schedule.agent import register
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai

from .test_ask_schedule import FakeScheduleLLM, _events, _register_data, _tomorrow


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _tool_use(name, args):
    return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}]}


@pytest.fixture
def schedule_llm(monkeypatch):
    fake = FakeScheduleLLM()
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    return fake


@pytest.fixture
def setup(client, family, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    other = client.get("/family-group/me", headers=b).json()["id"]
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return a, b, other


def _main(monkeypatch, question="질문"):
    seen = {}

    def fake_post(body):
        if len(body["messages"]) == 1:
            return _tool_use("ask_schedule", {"question": question})
        data = json.loads(body["messages"][-1]["content"][0]["content"])
        seen["tool_result"] = data
        return _text("카드를 확인해 주세요.")

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    return seen


def _ask(client, headers, **body):
    r = client.post("/ai-assistant/chat", json={"message": "질문", **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(client, headers, card, share=True):
    return client.post(
        "/schedule/agent/confirm",
        json={"action": card["pending_action"], "share": share},
        headers=headers,
    )


def test_share_register_comes_back_as_a_card_and_the_button_creates_both_calendars(
    client, setup, schedule_llm, monkeypatch
):
    a, b, other = setup
    seen = _main(monkeypatch)
    schedule_llm.data = _register_data(
        title="가족 모임", date=_tomorrow(), start_time="18:00:00", kind=1, share_ids=[other]
    )
    out = _ask(client, a)
    assert [c["action"] for c in out["confirm_cards"]] == ["register"]
    card = out["confirm_cards"][0]
    assert (
        card["kind"] == "schedule" and "수진" in card["title"] and card["shared_with"] == ["수진"]
    )
    assert any("가족 모임" in line for line in card["lines"])
    assert (
        "tool_result" not in seen
    )  # 직통 응답: 메인이 다시 말을 붙이지 않고 카드 제목이 그대로 답이다
    assert out["reply"] == card["title"]
    assert (
        _events(client, a) == [] and _events(client, b) == []
    )  # 버튼을 누르기 전에는 만들지 않는다

    done = _confirm(client, a, card)
    assert done.status_code == 200, done.text
    assert [e["title"] for e in _events(client, a)] == ["가족 모임"]
    assert [e["title"] for e in _events(client, b)] == ["가족 모임"]  # 받은 사람의 복사본


def test_card_button_can_register_only_mine(client, setup, schedule_llm, monkeypatch):
    a, b, other = setup
    _main(monkeypatch)
    schedule_llm.data = _register_data(
        title="가족 모임", date=_tomorrow(), kind=1, share_ids=[other]
    )
    card = _ask(client, a)["confirm_cards"][0]
    assert _confirm(client, a, card, share=False).status_code == 200
    assert [e["title"] for e in _events(client, a)] == ["가족 모임"] and _events(client, b) == []


def test_delete_comes_back_as_a_card_and_is_not_executed_until_confirmed(
    client, setup, schedule_llm, monkeypatch
):
    a, _, _ = setup
    created = client.post(
        "/schedule/events",
        json={"title": "치과", "start_date": _tomorrow(), "start_time": "14:00:00"},
        headers=a,
    ).json()
    _main(monkeypatch)
    schedule_llm.data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [],
        "target_id": created["id"],
        "changes": {
            "title": "",
            "date": "",
            "start_time": "",
            "end_time": "",
            "kind": 0,
            "place": "",
            "memo": "",
            "clear": [],
        },
    }
    out = _ask(client, a)
    card = out["confirm_cards"][0]
    assert card["action"] == "delete" and any("치과" in line for line in card["lines"])
    assert [e["title"] for e in _events(client, a)] == ["치과"]  # 아직 그대로
    assert _confirm(client, a, card).status_code == 200
    assert _events(client, a) == []


def test_edit_comes_back_as_a_card_with_the_changes(client, setup, schedule_llm, monkeypatch):
    a, _, _ = setup
    created = client.post(
        "/schedule/events",
        json={"title": "치과", "start_date": _tomorrow(), "start_time": "14:00:00"},
        headers=a,
    ).json()
    _main(monkeypatch)
    schedule_llm.data = {
        "intent": "edit",
        "reply": "",
        "event_ids": [],
        "target_id": created["id"],
        "changes": {
            "title": "",
            "date": "",
            "start_time": "16:00",
            "end_time": "",
            "kind": 0,
            "place": "",
            "memo": "",
            "clear": [],
        },
    }
    card = _ask(client, a)["confirm_cards"][0]
    assert card["action"] == "edit" and len(card["lines"]) >= 2  # 일정 한 줄 + 바뀌는 내용
    assert any(
        "→" in line and "{" not in line for line in card["lines"]
    )  # "시간: 14:00~15:00 → 16:00~17:00"
    assert _confirm(client, a, card).status_code == 200
    assert _events(client, a)[0]["start_time"].startswith("16:00")


def test_forged_card_payload_is_revalidated_by_the_server(client, setup, schedule_llm, monkeypatch):
    """앱이 돌려준 내용은 믿지 않는다: 다른 가족의 일정 id 로 바꿔 보내도 삭제되지 않는다."""
    a, _, _ = setup
    _main(monkeypatch)
    schedule_llm.data = _register_data(title="가족 모임", date=_tomorrow(), share_ids=[])
    out = _ask(client, a)  # 공유가 없어 바로 등록된다(카드 없음)
    assert out["confirm_cards"] == []
    forged = {"type": "delete", "event_id": "not-mine", "changes": {}, "draft": None}
    r = client.post("/schedule/agent/confirm", json={"action": forged, "share": True}, headers=a)
    assert r.status_code >= 400
    assert [e["title"] for e in _events(client, a)] == ["가족 모임"]


def test_room_answer_with_a_card_is_posted_and_the_card_stays_with_the_asker(
    client, setup, schedule_llm, monkeypatch
):
    a, b, other = setup
    _main(monkeypatch)
    schedule_llm.data = _register_data(title="가족 모임", date=_tomorrow(), share_ids=[other])
    out = _ask(client, a, audience="room")
    assert out["visibility"] == "room" and out["private_reasons"] == []
    assert out["posted_message_id"] is not None  # 답 글은 방에 남는다
    assert out["confirm_cards"]  # 확인 버튼은 질문한 사람 응답에만 있다
    assert [m["id"] for m in client.get("/family-chat/messages", headers=b).json()] == [
        out["posted_message_id"]
    ]


def test_schedule_agent_prompt_knows_whole_family_sharing():
    from app.features.schedule.agent import prompts

    assert "가족 전체" in prompts.CHAT_SYSTEM and "전원" in prompts.CHAT_SYSTEM
    assert (
        register.normalize
    )  # 말한 사람(나)은 공유 대상에서 코드가 빼므로 전원을 넣어도 자기 자신에게는 공유되지 않는다


def test_whole_family_words_are_spelled_out_as_share_targets(client, family):
    from app.features.schedule.agent.ask import with_whole_family
    from app.shared.db import SessionLocal
    from tests.helpers import join_family, signup

    a, _, group = family
    third = signup(client, "서연")
    assert join_family(client, a, group["invite_code"], third).status_code == 200
    me = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        text = with_whole_family(
            "토요일 6시 엄마 생신 가족 모두에게 공유해서 일정 잡아줘", db, group["id"], me
        )
        assert text.endswith("(공유 대상: 수진, 서연)") or text.endswith("(공유 대상: 서연, 수진)")
        # 공유를 말하지 않았거나 가족 전체를 말하지 않으면 그대로 둔다
        assert (
            with_whole_family("가족 모두 모이는 날 일정 잡아줘", db, group["id"], me)
            == "가족 모두 모이는 날 일정 잡아줘"
        )
        assert (
            with_whole_family("수진에게 공유해서 일정 잡아줘", db, group["id"], me)
            == "수진에게 공유해서 일정 잡아줘"
        )


@pytest.mark.parametrize("model_share_ids", [[], "one"])
def test_whole_family_share_always_targets_everyone_even_if_the_model_picks_fewer(
    client, family, monkeypatch, schedule_llm, model_share_ids
):
    from tests.helpers import join_family, signup

    a, b, group = family
    third = signup(client, "서연")
    assert join_family(client, a, group["invite_code"], third).status_code == 200
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    ids = {
        name: client.get("/family-group/me", headers=h).json()["id"]
        for name, h in (("b", b), ("c", third))
    }
    picked = [ids["c"]] if model_share_ids == "one" else []
    _main(monkeypatch, question="토요일 6시 엄마 생신 가족 모두에게 공유해서 일정 잡아줘")
    schedule_llm.data = _register_data(
        title="엄마 생신", date=_tomorrow(), start_time="18:00:00", kind=1, share_ids=picked
    )
    out = _ask(client, a)
    card = out["confirm_cards"][0]
    assert sorted(card["shared_with"]) == ["서연", "수진"]
    assert _confirm(client, a, card).status_code == 200
    for headers in (b, third):
        titles = [e["title"] for e in client.get("/schedule/events", headers=headers).json()]
        assert "엄마 생신" in titles
