"""모델이 생각 블록만 보내고 글 없이 끝내면(드물게 생긴다) 같은 대화로 한 번만 다시 부른다."""

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.db import SessionLocal

pytestmark = pytest.mark.usefixtures("client")

QUESTION = "배수필터 청소 주기"
FOUND = "배수필터는 한 달에 한 번 청소해요 [1]."
THINKING_ONLY = {"content": [{"type": "thinking", "thinking": "", "signature": "x"}]}


class Fake:
    """1번째는 검색 도구, 2번째는 shape(빈 답 또는 글), 3번째부터는 FOUND 를 돌려준다."""

    def __init__(self, second):
        self.second = second
        self.bodies: list[dict] = []

    def __call__(self, body):
        self.bodies.append(body)
        n = len(self.bodies)
        if n == 1:
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
        if n == 2:
            return self.second
        return {"content": [{"type": "text", "text": FOUND}]}


@pytest.fixture
def group(client, family, monkeypatch):
    a, _, grp = family
    monkeypatch.setattr(settings, "chat_verify_answer", False)
    monkeypatch.setattr(settings, "chat_retry_not_found", False)
    r = client.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "설명서",
            "title": "세탁기 설명서",
            "body_md": "# 세탁기 설명서\n[p.1]\n배수필터는 한 달에 한 번 청소합니다.",
        },
        headers=a,
    )
    assert r.status_code == 201, r.text
    return grp


def _ask(group, fake):
    with SessionLocal() as db:
        return rag_chat.ask(db, group["id"], QUESTION, post=fake)


def test_empty_reply_is_asked_once_more(group):
    fake = Fake(THINKING_ONLY)
    r = _ask(group, fake)
    assert len(fake.bodies) == 3  # 검색 도구, 빈 답, 다시 부른 답
    assert r.answer == FOUND
    assert fake.bodies[2]["tool_choice"] == {"type": "none"}


def test_normal_reply_is_not_asked_again(group):
    fake = Fake({"content": [{"type": "text", "text": "정상 답이에요 [1]."}]})
    r = _ask(group, fake)
    assert len(fake.bodies) == 2
    assert r.answer == "정상 답이에요 [1]."
