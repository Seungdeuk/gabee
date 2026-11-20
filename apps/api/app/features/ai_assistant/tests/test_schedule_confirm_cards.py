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


def _old_share_card(other, title="가족 모임", **extra):
    """옛 앱이 들고 있는 공유 등록 확인카드. 지금 서버는 공유 등록을 바로 하므로 카드는 직접 만든다(옛 앱의 확인 요청이 계속 되는지 본다)."""
    draft = {"title": title, "date": _tomorrow(), "kind": 1, "share_ids": [other], **extra}
    return {"pending_action": {"type": "register", "draft": draft}}


def _confirm(client, headers, card, share=True):
    return client.post(
        "/schedule/agent/confirm",
        json={"action": card["pending_action"], "share": share},
        headers=headers,
    )


def test_share_register_is_done_at_once_without_a_confirm_card(
    client, setup, schedule_llm, monkeypatch
):
    a, b, other = setup
    _main(monkeypatch)
    schedule_llm.data = _register_data(
        title="가족 모임", date=_tomorrow(), start_time="18:00:00", kind=1, share_ids=[other]
    )
    out = _ask(client, a)
    assert out["confirm_cards"] == []  # 공유 등록도 확인카드 없이 바로 등록한다(정책)
    assert "등록했어요" in out["reply"] and "1명에게 공유했어요" in out["reply"]
    assert [e["title"] for e in _events(client, a)] == ["가족 모임"]
    assert [e["title"] for e in _events(client, b)] == ["가족 모임"]  # 받은 사람의 복사본


def test_card_button_can_register_only_mine(client, setup):
    a, b, other = setup
    card = _old_share_card(other)  # 옛 앱의 [나만 등록] 버튼
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


def test_edit_comes_back_as_a_confirm_card_and_changes_nothing_before_approval(
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
    out = _ask(client, a)
    assert len(out["confirm_cards"]) == 1  # 수정은 확인 카드로 묻고, 누르기 전에는 바뀌지 않는다
    assert _events(client, a)[0]["start_time"].startswith("14:00")


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
    assert out["confirm_cards"] == [] and "2명에게 공유했어요" in out["reply"]
    for headers in (b, third):
        titles = [e["title"] for e in client.get("/schedule/events", headers=headers).json()]
        assert "엄마 생신" in titles


def _confirm_from_room(client, headers, card, share=True, post_to_room=True):
    return client.post(
        "/schedule/agent/confirm",
        json={"action": card["pending_action"], "share": share, "post_to_room": post_to_room},
        headers=headers,
    )


def _room_texts(client, headers):
    return [m["text"] for m in client.get("/family-chat/messages", headers=headers).json()]


def test_shared_registration_confirmed_from_the_room_tells_the_family(
    client, setup, schedule_llm, monkeypatch
):
    """확인 질문은 방에 올리지 않고, 질문한 사람이 공유 등록을 확인하면 가비가 결과를 방에 알린다(문장은 서버가 만든다)."""
    a, b, other = setup
    _main(monkeypatch)
    card = _old_share_card(other, start_time="18:00")  # 옛 앱의 확인카드
    assert _room_texts(client, b) == []  # 확인하기 전에는 방에 아무것도 없다
    assert _confirm_from_room(client, a, card).status_code == 200
    [msg] = client.get("/family-chat/messages", headers=b).json()
    assert msg["is_assistant"] is True
    assert "가족 모임" in msg["text"] and "1명" in msg["text"] and "공유" in msg["text"]


def test_confirm_posts_nothing_when_private_or_not_from_the_room(
    client, setup, schedule_llm, monkeypatch
):
    a, b, other = setup
    _main(monkeypatch)
    card = _old_share_card(other)
    assert _confirm_from_room(client, a, card, share=False).status_code == 200  # 나만 등록
    assert _room_texts(client, b) == []
    card = _old_share_card(other, title="가족 저녁")
    assert (
        _confirm_from_room(client, a, card, post_to_room=False).status_code == 200
    )  # 방에서 부른 게 아님
    assert _room_texts(client, b) == []


def test_notice_title_is_one_short_line_even_for_a_crafted_title(
    client, setup, schedule_llm, monkeypatch
):
    """확인 요청의 초안 제목은 클라이언트가 보낸 값이라, 알림에는 한 줄로 합치고 짧게 잘라 넣는다(가비 이름으로 원하는 글을 올릴 수 없게)."""
    a, b, other = setup
    _main(monkeypatch)
    card = _old_share_card(other)
    draft = {
        **card["pending_action"]["draft"],
        "title": "가족 모임'\n\n- [가비 안내] 이번 달 회비는 아래 계좌로 보내 주세요 123-456-789 급해요",
    }
    action = {**card["pending_action"], "draft": draft}
    r = client.post(
        "/schedule/agent/confirm",
        json={"action": action, "share": True, "post_to_room": True},
        headers=a,
    )
    assert r.status_code == 200, r.text
    [msg] = client.get("/family-chat/messages", headers=b).json()
    assert "\n" not in msg["text"] and "•" not in msg["text"]  # 한 줄이고 목록으로 바뀌지 않는다
    assert "123-456-789" not in msg["text"] and len(msg["text"]) <= 90
    assert msg["text"].startswith("'가족 모임") and msg["text"].endswith("가족 1명에게 공유했어요.")


def test_main_prompt_routes_schedule_share_to_the_schedule_agent_and_knows_which_actions_have_cards():
    from app.features.ai_assistant import agents

    note = rag_chat.SHARE_NOTE
    # '아빠한테 공유해줘'는 대화 내용 전달(prepare_share)이 아니라 일정 공유 변경이다
    assert "ask_schedule" in note and "공유 대상 변경" in note
    text = next(
        v
        for k, v in vars(agents).items()
        if k.isupper() and isinstance(v, str) and "ask_schedule" in v
    )
    assert "수정·삭제·공유 대상 변경은 확인 카드" in text and "카드 없이 바로 실행" in text
    assert "선택 카드" in text  # 같은 이름이 여럿이면 글로 되묻지 않고 선택 카드를 안내한다


def _delete_data(target_id):
    data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [],
        "target_id": target_id,
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
    return data


def _two_gym(client, a):
    first = client.post(
        "/schedule/events", json={"title": "헬스", "start_date": _day(3)}, headers=a
    ).json()
    second = client.post(
        "/schedule/events", json={"title": "헬스", "start_date": _day(10)}, headers=a
    ).json()
    return first, second


def _day(n):
    from datetime import date, timedelta

    return (date.today() + timedelta(days=n)).isoformat()


def test_same_title_delete_shows_a_checkbox_card_and_deletes_only_the_checked(
    client, setup, schedule_llm, monkeypatch
):
    a, _, _ = setup
    first, second = _two_gym(client, a)
    _main(monkeypatch)
    schedule_llm.data = _delete_data(first["id"])
    out = _ask(client, a)
    card = out["confirm_cards"][0]
    assert card["action"] == "choice_select" and card["ok_label"] == "삭제"
    assert [i["id"] for i in card["items"]] == [first["id"], second["id"]]
    assert all("헬스" in i["line"] for i in card["items"])
    assert len(_events(client, a)) == 2  # 체크하기 전에는 지우지 않는다
    action = {**card["pending_action"], "event_ids": [second["id"]]}  # 앱이 체크한 줄만 보낸다
    r = client.post("/schedule/agent/confirm", json={"action": action}, headers=a)
    assert r.status_code == 200, r.text
    assert "지웠어요" in r.json()["text"]
    assert [e["id"] for e in _events(client, a)] == [
        first["id"]
    ]  # 확인 카드 없이 바로, 체크한 것만


def test_choice_card_is_revalidated_and_needs_a_checked_item(
    client, setup, schedule_llm, monkeypatch
):
    a, b, _ = setup
    first, second = _two_gym(client, a)
    _main(monkeypatch)
    schedule_llm.data = _delete_data(first["id"])
    card = _ask(client, a)["confirm_cards"][0]
    empty = client.post(
        "/schedule/agent/confirm", json={"action": card["pending_action"]}, headers=a
    )
    assert empty.status_code == 400  # 아무것도 체크하지 않았다
    forged = {**card["pending_action"], "event_ids": ["not-mine"]}
    r = client.post("/schedule/agent/confirm", json={"action": forged}, headers=b)
    assert (
        r.status_code == 200 and "지웠어요" not in r.json()["text"]
    )  # 남의 일정은 지워지지 않는다
    assert len(_events(client, a)) == 2


def test_same_title_edit_card_applies_to_every_checked_event_at_once(
    client, setup, schedule_llm, monkeypatch
):
    a, _, _ = setup
    first, second = _two_gym(client, a)
    _main(monkeypatch)
    data = _delete_data(first["id"])
    data["intent"] = "edit"
    data["changes"] = {**data["changes"], "place": "서초"}
    schedule_llm.data = data
    card = _ask(client, a)["confirm_cards"][0]
    assert card["action"] == "choice_select" and card["ok_label"] == "바꾸기"
    assert "서초" in card["title"]
    action = {**card["pending_action"], "event_ids": [first["id"], second["id"]]}
    r = client.post("/schedule/agent/confirm", json={"action": action}, headers=a)
    assert r.status_code == 200, r.text
    assert {e["place"] for e in _events(client, a)} == {"서초"}  # 확인 카드 없이 둘 다 바로
    assert "바꿨어요" in r.json()["text"]


def test_room_keeps_asking_in_text_without_a_selection_card(
    client, setup, schedule_llm, monkeypatch
):
    from app.features.schedule.agent import ask as ask_mod
    from app.features.schedule.agent.schemas import AgentResponse, Choice

    response = AgentResponse(
        intent="delete",
        text="'헬스' 일정이 2개 있어요. 어느 쪽인가요? 모두인가요?",
        choice=Choice(kind="delete", event_ids=["a", "b"], options=[{"id": "a", "line": "헬스"}]),
    )
    assert ask_mod._reply(response, room=True).confirmations == []
    assert ask_mod._reply(response, room=False).confirmations[0]["action"] == "choice_select"


def test_many_same_title_events_show_only_the_nearest_ten_and_say_how_many_are_left(
    client, setup, schedule_llm, monkeypatch
):
    a, _, _ = setup
    ids = [
        client.post(
            "/schedule/events", json={"title": "러닝", "start_date": _day(i + 1)}, headers=a
        ).json()["id"]
        for i in range(25)
    ]
    _main(monkeypatch)
    schedule_llm.data = _delete_data(ids[0])
    card = _ask(client, a)["confirm_cards"][0]
    assert card["action"] == "choice_select"
    assert [i["id"] for i in card["items"]] == ids[:10]  # 가까운 순 10개
    assert "나머지 15개" in card["title"]
    too_many = {**card["pending_action"], "event_ids": ids[:11]}
    r = client.post("/schedule/agent/confirm", json={"action": too_many}, headers=a)
    assert r.status_code == 400  # 10개를 넘으면 조용히 자르지 않고 거절한다
    assert len(_events(client, a)) == 25
