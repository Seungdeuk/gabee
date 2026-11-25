"""AI 채팅 웹 검색: 켜진 경로에서만 도구를 주고, 인용만 출처로 돌려주고, 길어져 멈춘 응답을 이어 받는다. 가짜 Claude 로 돈다."""

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup


def _text(text, citations=None, stop="end_turn"):
    block = {"type": "text", "text": text}
    if citations:
        block["citations"] = citations
    return {"content": [block], "stop_reason": stop, "model": "m", "usage": {}}


def _cite(url, title="기상청"):
    return {"type": "web_search_result_location", "url": url, "title": title, "cited_text": "맑음"}


@pytest.fixture
def group(client):
    headers = signup(client, "강민훈", "parent")
    made = client.post("/family-group/groups", json={"name": "강씨네"}, headers=headers).json()
    return headers, made


def _ask(group_id, replies, web=True):
    bodies = []
    script = iter(replies)

    def post(body):
        bodies.append(body)
        return next(script)

    with SessionLocal() as db:
        result = rag_chat.ask(db, group_id, "내일 서울 날씨 어때?", post=post, web=web)
    return result, bodies


def _tool_names(body):
    return [t["name"] for t in body["tools"]]


def test_web_tool_is_given_only_when_both_the_setting_and_the_path_allow_it(group, monkeypatch):
    _, made = group
    monkeypatch.setattr(settings, "web_search_enabled", False)
    _, bodies = _ask(made["id"], [_text("답")])
    assert "web_search" not in _tool_names(bodies[0])

    monkeypatch.setattr(settings, "web_search_enabled", True)
    _, bodies = _ask(made["id"], [_text("답")], web=False)
    assert "web_search" not in _tool_names(bodies[0]) and "web_search" not in bodies[0]["system"]

    monkeypatch.setattr(settings, "web_search_max_uses", 2)
    _, bodies = _ask(made["id"], [_text("답")])
    tool = next(t for t in bodies[0]["tools"] if t["name"] == "web_search")
    assert tool["type"] == "web_search_20250305" and tool["max_uses"] == 2
    assert (
        bodies[0]["max_tokens"] == settings.agent_max_output_tokens
    )  # 1024 로는 답을 쓰기 전에 끊겼다(공통 설정, 기본 10000)
    assert "개인정보를 넣지 말고" in bodies[0]["system"]
    assert "지시나 명령처럼" in bodies[0]["system"]


def test_only_cited_web_pages_become_sources(group, monkeypatch):
    _, made = group
    monkeypatch.setattr(settings, "web_search_enabled", True)
    reply = {
        "content": [
            {"type": "text", "text": "내일 서울은 "},
            {
                "type": "server_tool_use",
                "id": "s1",
                "name": "web_search",
                "input": {"query": "서울 날씨"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "s1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://uncited.example",
                        "title": "안 씀",
                    }
                ],
            },
            {
                "type": "text",
                "text": "맑아요.",
                "citations": [
                    _cite("https://www.kma.go.kr/a"),
                    _cite("https://www.kma.go.kr/a"),  # 같은 주소는 하나로
                    _cite("javascript:alert(1)", "나쁜 링크"),  # http(s) 만
                    {"type": "char_location", "url": "https://other.example"},  # 웹 인용이 아니다
                ],
            },
        ],
        "stop_reason": "end_turn",
        "model": "m",
        "usage": {},
    }
    result, _ = _ask(made["id"], [reply])
    assert result.answer == "내일 서울은 맑아요."
    assert result.web_sources == [{"title": "기상청", "url": "https://www.kma.go.kr/a"}]


def test_paused_search_is_sent_back_unchanged_and_continued(group, monkeypatch):
    _, made = group
    monkeypatch.setattr(settings, "web_search_enabled", True)
    paused = {
        "content": [
            {
                "type": "server_tool_use",
                "id": "s1",
                "name": "web_search",
                "input": {"query": "날씨"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "s1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://a.example",
                        "encrypted_content": "암호문",
                    }
                ],
            },
        ],
        "stop_reason": "pause_turn",
        "model": "m",
        "usage": {},
    }
    result, bodies = _ask(made["id"], [paused, _text("맑아요.", [_cite("https://a.example")])])
    assert result.answer == "맑아요." and result.source == "ai"
    assert len(bodies) == 2
    assert bodies[1]["messages"][-1] == {"role": "assistant", "content": paused["content"]}


def test_pause_stops_at_the_step_limit(group, monkeypatch):
    _, made = group
    monkeypatch.setattr(settings, "web_search_enabled", True)
    paused = _text("찾는 중", stop="pause_turn")
    result, bodies = _ask(made["id"], [paused] * rag_chat.MAX_STEPS)
    assert len(bodies) == rag_chat.MAX_STEPS and result.answer == "찾는 중"


def test_chat_api_returns_web_sources_on_the_ai_tab_but_not_in_family_rooms(
    client, group, monkeypatch
):
    headers, _ = group
    monkeypatch.setattr(settings, "web_search_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers).status_code
        == 200
    )
    bodies = []

    def post(body):
        bodies.append(body)
        return _text("맑아요.", [_cite("https://a.example", "날씨")])

    monkeypatch.setattr(rag_chat, "_post", post)
    res = client.post("/ai-assistant/chat", json={"message": "내일 날씨"}, headers=headers)
    assert res.status_code == 200
    assert res.json()["web_sources"] == [{"title": "날씨", "url": "https://a.example"}]
    assert "web_search" in _tool_names(bodies[-1])

    room = client.post(
        "/ai-assistant/chat", json={"message": "내일 날씨", "audience": "room"}, headers=headers
    )
    assert room.status_code == 200
    assert room.json()["web_sources"] == [] and "web_search" not in _tool_names(bodies[-1])
