"""위치 기록 질문 에이전트 시험. 가짜 LLM 만 쓰고 실제 모델은 부르지 않는다."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.features.ai_assistant.knowledge.embedding import HashingEmbedder, set_embedder
from app.features.family_group.models import User
from app.features.location import agent, rag
from app.features.location.summary import Span
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from tests.helpers import allow_ai

TODAY = datetime(2026, 11, 10, 9, 0)


@pytest.fixture
def hashing():
    embedder = HashingEmbedder()
    set_embedder(embedder)
    yield embedder
    set_embedder(None)


def _t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute)


class FakeLLM:
    """첫 호출에는 지정한 도구 호출을, 도구 결과를 받은 다음 호출에는 마지막 도구 결과를 그대로 요약한 답을 돌려준다."""

    def __init__(self, tool_args: dict | None, final: str = "답변"):
        self.tool_args = tool_args
        self.final = final
        self.requests: list[dict] = []

    def __call__(self, body: dict) -> dict:
        self.requests.append(json.loads(json.dumps(body, default=str)))
        usage = {"input_tokens": 10, "output_tokens": 5}
        last = body["messages"][-1]
        if (
            self.tool_args is not None
            and last["role"] == "user"
            and isinstance(last["content"], str)
        ):
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "search_location_history",
                        "input": self.tool_args,
                    }
                ],
                "usage": usage,
            }
        return {"content": [{"type": "text", "text": self.final}], "usage": usage}

    @property
    def tool_results(self) -> str:
        """LLM 이 받은 도구 결과 글 전부."""
        out = []
        for req in self.requests:
            for m in req["messages"]:
                if isinstance(m["content"], list):
                    out += [
                        c.get("content", "") for c in m["content"] if c.get("type") == "tool_result"
                    ]
        return " ".join(out)


@pytest.fixture
def world(client, family, hashing):
    """지민(소유자, 부모)·수진(구성원). 수진은 학원, 지민은 회사에 머문 기록."""
    a, b, group = family
    ids = {
        n: client.get("/family-group/me", headers=h).json()["id"] for n, h in (("a", a), ("b", b))
    }
    spans = [
        Span("a", "지민", _t(9, 0), _t(9, 8), "stay", "집"),
        Span("a", "지민", _t(9, 8), _t(9, 18), "stay", "느티나무 회사"),
        Span("b", "수진", _t(9, 0), _t(9, 14), "stay", "푸른샘 학교"),
        Span("b", "수진", _t(9, 14), _t(9, 19), "stay", "별빛 학원"),
    ]
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.id == ids["a"])).one()
        gid = me.active_group_id
        rag.index_spans(db, gid, ids, spans, hashing)
        db.commit()
    return a, b, ids, gid


def _ask(user_id: str, gid: str, question: str, fake: FakeLLM, hashing):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        # 도구와 권한 규칙만 본다(관문의 동의·한도는 아래 엔드포인트 시험이 본다)
        return agent.ask(
            db, gid, user, question, post=fake, today=TODAY, embedder=hashing, guarded=False
        )


def test_parent_asks_about_a_child_and_llm_gets_only_summary_sentences(world, hashing):
    _, _, ids, gid = world
    fake = FakeLLM(
        {"person": "수진", "date": "2026-11-09", "time": "16:00", "query": "어디"},
        "수진은 별빛 학원에 있었어요",
    )
    reply = _ask(ids["a"], gid, "11월 9일 오후 4시에 수진이 어디 있었어?", fake, hashing)
    assert reply.can_answer and reply.answer == "수진은 별빛 학원에 있었어요"
    assert [c["name"] for c in reply.tool_calls] == ["search_location_history"]
    text = fake.tool_results
    assert "별빛 학원에서 머묾" in text and "느티나무 회사" not in text  # 수진만 찾았다
    assert not any(ch in text for ch in ("lat", "lng", "latitude"))  # 좌표 필드가 없다
    assert fake.requests[0]["tools"][0]["name"] == "search_location_history"


def test_child_cannot_read_others_records_even_if_llm_asks_for_them(world, hashing):
    _, _, ids, gid = world
    fake = FakeLLM({"person": "지민", "query": "회사"}, "권한이 없어요")
    reply = _ask(ids["b"], gid, "지민이 어디 있었어?", fake, hashing)
    assert reply.can_answer
    assert "볼 권한이 없어요" in fake.tool_results
    assert "느티나무 회사" not in fake.tool_results and "머묾" not in fake.tool_results
    system = fake.requests[0]["system"]
    assert (
        "볼 수 있는 사람: 수진" in system
        and "지민," not in system.split("볼 수 있는 사람:")[1].split(".")[0]
    )


def test_child_asking_without_name_only_searches_own_records(world, hashing):
    _, _, ids, gid = world
    fake = FakeLLM({"query": "어디"})
    _ask(ids["b"], gid, "어디 있었지?", fake, hashing)
    assert "수진" in fake.tool_results and "지민" not in fake.tool_results


def test_parent_can_list_everyone_and_unknown_name_is_reported(world, hashing):
    _, _, ids, gid = world
    fake = FakeLLM({"query": "어디"})
    _ask(ids["a"], gid, "다들 어디 있었어?", fake, hashing)
    assert "수진" in fake.tool_results and "지민" in fake.tool_results
    fake = FakeLLM({"person": "없는사람", "query": "어디"})
    _ask(ids["a"], gid, "없는사람 어디야?", fake, hashing)
    assert "그런 이름이 없어요" in fake.tool_results


def test_system_prompt_has_today_and_rules(world, hashing):
    _, _, ids, gid = world
    fake = FakeLLM(None, "저는 가족 위치 기록만 도와드릴 수 있어요")
    reply = _ask(ids["a"], gid, "내일 날씨 어때?", fake, hashing)
    assert reply.tool_calls == []
    system = fake.requests[0]["system"]
    assert "2026년 11월 10일 화요일" in system and "좌표나 주소는 알려 주지 않는다" in system


def test_non_member_is_rejected(world, other_family, hashing):
    _, _, _, gid = world
    with SessionLocal() as db:
        outsider = db.scalars(select(User).where(User.name == "남")).one()
        with pytest.raises(ApiError) as e:
            agent.ask(
                db, gid, outsider, "어디야?", post=FakeLLM(None), today=TODAY, embedder=hashing
            )
    assert e.value.status == 403


def test_location_agent_has_its_own_limit_bucket():
    limits, features = ai_guard._bucket_of(agent.FEATURE)
    assert features == (agent.FEATURE,)
    assert limits.per_user_per_day == settings.ai_location_agent_max_calls_per_user_per_day == 30
    assert limits.per_group_per_day == settings.ai_location_agent_max_calls_per_group_per_day == 100


def test_ask_endpoint_switch_login_and_llm_failure(client, family, monkeypatch):
    a, b, _ = family
    assert client.post("/location/ask", json={"question": "어디야?"}).status_code == 401
    assert (
        client.post("/location/ask", json={"question": "어디야?"}, headers=a).status_code == 503
    )  # 스위치 꺼짐
    monkeypatch.setattr(settings, "location_enabled", True)
    assert client.post("/location/ask", json={"question": ""}, headers=a).status_code == 422
    allow_ai(client, a, monkeypatch)
    r = client.post("/location/ask", json={"question": "어디야?"}, headers=a)
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"  # 시험에는 API 키가 없다


def test_ask_endpoint_answers_with_fake_llm(client, family, hashing, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(settings, "location_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    allow_ai(client, a, monkeypatch)
    fake = FakeLLM(None, "저는 가족 위치 기록만 도와드릴 수 있어요")
    monkeypatch.setattr("app.shared.llm.agent._post", fake)
    r = client.post("/location/ask", json={"question": "날씨 알려줘"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json() == {"answer": "저는 가족 위치 기록만 도와드릴 수 있어요", "used_tool": False}
    assert datetime.now(UTC)  # 호출 기록이 남는지는 관문 시험이 본다
