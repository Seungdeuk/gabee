"""가족 채팅 대화 자동 요약(AI). 실제 Anthropic 을 부르지 않고 llm.complete 를 가짜로 바꿔 끼운다."""

import logging

import httpx
import pytest

from app.features.family_chat import summary_service
from app.shared.config import Settings, settings
from app.shared.llm import client as llm
from tests.helpers import signup

URL = "/family-chat/summary"


class FakeLLM:
    """llm.complete 대역: 받은 프롬프트를 모아 두고 정해 둔 요약을 돌려준다."""

    def __init__(
        self, reply="- 주말에 할머니 댁에 가기로 정했어요\n- 엄마가 장을 보기로 했어요", fail=False
    ):
        self.reply, self.fail, self.calls = reply, fail, []

    def __call__(self, prompt, system=None, max_tokens=1024, timeout=30.0):
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
        if self.fail:
            raise llm.LLMUnavailable("AI 호출에 실패했어요 (HTTPStatusError)")
        return self.reply


@pytest.fixture
def ai(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(summary_service.llm, "complete", fake)
    return fake


def say(client, headers, text):
    r = client.post("/family-chat/messages", json={"text": text}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def talk(client, a, b, n=4):
    ids = []
    for i in range(n):
        ids.append(say(client, a if i % 2 == 0 else b, f"대화 {i}번째 이야기")["id"])
    return ids


# ---------- 요약 ----------
def test_family_member_gets_a_summary_of_recent_conversation(client, family, ai):
    a, b, _ = family
    say(client, a, "이번 주말에 할머니 댁에 갈까요?")
    say(client, b, "좋아요. 토요일 오전 10시에 출발해요")
    say(client, a, "그럼 제가 장을 볼게요")
    r = client.post(URL, json={}, headers=b)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"].startswith("- 주말에 할머니 댁에")
    assert body["message_count"] == 3 and body["from_message_id"] < body["to_message_id"]
    assert body["model"] == settings.llm_model and body["generated_at"]
    prompt = ai.calls[0]["prompt"]
    assert (
        prompt.index("할머니 댁에 갈까요")
        < prompt.index("토요일 오전 10시")
        < prompt.index("장을 볼게요")
    )  # 오래된 순
    assert "지민:" in prompt and "수진:" in prompt  # 이름만 보낸다
    assert "개인정보" in ai.calls[0]["system"] and ai.calls[0]["max_tokens"] <= 1024


def test_only_this_groups_conversation_is_sent_to_the_ai(client, family, ai):
    a, b, _ = family
    talk(client, a, b, 4)
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    for i in range(3):
        say(client, outsider, f"다른 가족의 비밀 이야기 {i}")
    assert client.post(URL, json={}, headers=a).status_code == 200
    assert "비밀 이야기" not in ai.calls[0]["prompt"]
    ai.calls.clear()
    assert client.post(URL, json={}, headers=outsider).status_code == 200
    assert "대화 0번째" not in ai.calls[0]["prompt"]


def test_range_options_limit_and_after_id(client, family, ai):
    a, b, _ = family
    ids = talk(client, a, b, 8)
    r = client.post(URL, json={"limit": 4}, headers=a).json()
    assert r["message_count"] == 4 and r["from_message_id"] == ids[4]  # 최근 4개
    r = client.post(URL, json={"after_id": ids[4]}, headers=a).json()
    assert r["from_message_id"] == ids[5] and r["to_message_id"] == ids[7]
    assert client.post(URL, json={"limit": 0}, headers=a).status_code == 422
    assert client.post(URL, json={"limit": 301}, headers=a).status_code == 422


def test_long_conversation_is_trimmed_from_the_oldest_side(client, family, ai, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(settings, "chat_summary_max_chars", 120)
    for i in range(10):
        say(client, a if i % 2 == 0 else b, f"{i}번 메시지 " + "가" * 20)
    body = client.post(URL, json={}, headers=a).json()
    prompt = ai.calls[0]["prompt"]
    assert (
        body["message_count"] < 10 and "9번 메시지" in prompt and "0번 메시지" not in prompt
    )  # 최신 대화를 남긴다
    assert body["to_message_id"] == client.get("/family-chat/messages", headers=a).json()[-1]["id"]


def test_too_few_messages_is_a_clear_400_and_calls_nothing(client, family, ai):
    a, _, _ = family
    say(client, a, "안녕")
    r = client.post(URL, json={}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "too_few_messages"
    assert ai.calls == []


# ---------- 설정·오류 ----------
def test_without_an_api_key_the_feature_says_it_is_not_configured(client, family, monkeypatch):
    a, b, _ = family
    talk(client, a, b)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post(URL, json={}, headers=a)
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"


def test_ai_failure_is_503_and_never_leaks_the_conversation(client, family, ai, caplog):
    a, b, _ = family
    say(client, a, "비밀번호 1234 는 아무한테도 말하지 마")
    say(client, b, "알겠어요")
    say(client, a, "계좌는 110-123-456789 예요")
    ai.fail = True
    with caplog.at_level(logging.DEBUG):
        r = client.post(URL, json={}, headers=a)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"
    assert "1234" not in r.text and "110-123" not in r.text
    assert (
        "1234" not in caplog.text and "110-123" not in caplog.text
    )  # 대화 글자는 로그에도 남기지 않는다


def test_summary_requests_are_rate_limited_per_user(client, family, ai, monkeypatch):
    a, b, _ = family
    talk(client, a, b)
    monkeypatch.setattr(settings, "chat_summary_max_per_hour", 2)
    assert client.post(URL, json={}, headers=a).status_code == 200
    assert client.post(URL, json={}, headers=a).status_code == 200
    blocked = client.post(URL, json={}, headers=a)
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_requests"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert client.post(URL, json={}, headers=b).status_code == 200  # 다른 사람의 한도와 따로 센다
    assert len(ai.calls) == 3


@pytest.fixture(autouse=True)
def _reset_limiter():
    summary_service.limiter.reset()
    yield
    summary_service.limiter.reset()


def test_needs_a_login_and_a_family(client, ai):
    assert client.post(URL, json={}).status_code == 401
    loner = signup(client, "혼자")
    r = client.post(URL, json={}, headers=loner)
    assert r.status_code == 400 and r.json()["code"] == "no_group"
    assert ai.calls == []


# ---------- 모델 선택: ANTHROPIC_MODEL ----------
def test_anthropic_model_env_selects_the_model(monkeypatch):
    for name in ("ANTHROPIC_MODEL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert Settings(_env_file=None).llm_model == "claude-haiku-5-5"  # 기본값
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert Settings(_env_file=None).llm_model == "claude-sonnet-5-5"
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5-5")  # 둘 다 있으면 ANTHROPIC_MODEL 이 먼저
    assert Settings(_env_file=None).llm_model == "claude-sonnet-5-5"
    monkeypatch.delenv("ANTHROPIC_MODEL")
    assert Settings(_env_file=None).llm_model == "claude-opus-5-5"  # 예전 이름도 읽는다
    monkeypatch.setenv("ANTHROPIC_MODEL", "   ")
    assert Settings(_env_file=None).llm_model == "claude-haiku-5-5"  # 비어 있으면 기본값


def test_the_configured_model_is_what_the_anthropic_request_uses(monkeypatch):
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "요약"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key-not-real")
    monkeypatch.setattr(settings, "llm_model", "claude-sonnet-5-5")
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.complete("안녕", system="시스템") == "요약"
    assert sent["body"]["model"] == "claude-sonnet-5-5" and sent["body"]["system"] == "시스템"
    assert sent["url"] == llm.API_URL and sent["headers"]["x-api-key"] == "test-key-not-real"
