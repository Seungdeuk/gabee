"""기권 초안 재검색(chat_retry_not_found): 초안이 '찾지 못했다'면 상위 문서 안을 코드가 다시 찾아 한 번만 더 답하게 한다."""

import json

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

QUESTION = "배수필터 청소 주기"
GIVE_UP = "배수필터 청소 주기는 찾지 못했어요. 원본 보기로 확인해 보세요."
FOUND = "배수필터는 한 달에 한 번 청소해요 [1]."


def _add(client, headers, **kw):
    r = client.post("/ai-assistant/knowledge/items", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class Fake:
    """1번째 호출은 검색 도구, 2번째는 first 답, 재검색 뒤 호출(마지막 user 가 tool_result 이고 no_tools)은 second 를 돌려준다."""

    def __init__(self, first, second):
        self.first, self.second = first, second
        self.bodies: list[dict] = []

    def __call__(self, body):
        self.bodies.append(body)
        if len(self.bodies) == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "search_knowledge",
                        "input": {"query": "배수필터"},
                    }
                ]
            }
        if len(self.bodies) == 2:
            return {"content": [{"type": "text", "text": self.first}]}
        return {"content": [{"type": "text", "text": self.second}]}


@pytest.fixture
def setup(client, family, other_family, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(settings, "chat_verify_answer", False)
    monkeypatch.setattr(settings, "chat_retry_not_found", True)
    _add(
        client,
        a,
        kind_label="설명서",
        title="세탁기 설명서",
        body_md="# 세탁기 설명서\n[p.1]\n배수필터는 한 달에 한 번 청소합니다.",
    )
    _add(
        client,
        other_family,
        kind_label="설명서",
        title="남의 집 설명서",
        body_md="# 남의 집 설명서\n배수필터 청소는 비밀 주기 99일마다 합니다.",
    )
    return group


def _ask(group, fake):
    with SessionLocal() as db:
        return rag_chat.ask(db, group["id"], QUESTION, post=fake)


def _retry_results(fake) -> str:
    """재검색 뒤 보낸 요청(3번째)의 tool_result 글."""
    last = fake.bodies[2]["messages"][-1]
    return json.dumps(last["content"], ensure_ascii=False)


def test_give_up_draft_triggers_exactly_one_retry(setup):
    fake = Fake(GIVE_UP, FOUND)
    r = _ask(setup, fake)
    assert len(fake.bodies) == 3  # 검색 도구, 초안, 재검색 뒤 답: 재검색 호출은 한 번뿐
    assert r.answer == FOUND
    assert [c["name"] for c in r.tool_calls] == ["search_knowledge", "retry_search"]
    assert fake.bodies[2]["tool_choice"] == {"type": "none"}
    assert "한 달에 한 번 청소" in _retry_results(fake)


def test_second_give_up_is_kept_without_third_call(setup):
    fake = Fake(GIVE_UP, "그 내용은 찾지 못했어요.")
    r = _ask(setup, fake)
    assert len(fake.bodies) == 3
    assert r.answer == "그 내용은 찾지 못했어요."


def test_normal_answer_does_not_retry(setup):
    fake = Fake(FOUND, "쓰이면 안 되는 답")
    r = _ask(setup, fake)
    assert len(fake.bodies) == 2
    assert r.answer == FOUND
    assert all(c["name"] != "retry_search" for c in r.tool_calls)


def test_other_group_records_are_not_included(setup):
    fake = Fake(GIVE_UP, FOUND)
    r = _ask(setup, fake)
    text = _retry_results(fake)
    assert "비밀 주기" not in text and "남의 집" not in text
    assert all("남의 집" not in s["title"] for s in r.sources)


def test_disabled_setting_does_not_retry(setup, monkeypatch):
    monkeypatch.setattr(settings, "chat_retry_not_found", False)
    fake = Fake(GIVE_UP, FOUND)
    r = _ask(setup, fake)
    assert len(fake.bodies) == 2
    assert r.answer == GIVE_UP
    assert all(c["name"] != "retry_search" for c in r.tool_calls)
