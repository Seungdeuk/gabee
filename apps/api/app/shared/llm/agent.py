"""도구를 부르며 답하는 에이전트 한 개를 돌리는 공통 코드(Anthropic Messages API 의 tool_use 반복).

기능 코드(예: billing/agent.py)는 SDK 를 직접 부르지 않고 여기만 쓴다. 도구는 서버 쪽 함수라서 어느 가족 그룹·사용자의
데이터를 볼지는 도구를 만든 코드가 정하고, LLM 은 조회 조건(월·날짜 등)만 고른다.
`post` 는 테스트에서 가짜 LLM 을 끼우는 자리다."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from app.shared.config import settings
from app.shared.errors import ApiError

from .client import API_URL, API_VERSION, LLMUnavailable

Post = Callable[[dict], dict]
MAX_TOOL_RESULT_CHARS = 12000


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[dict], dict]

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class AgentReply:
    """에이전트의 답. can_answer 가 False 면 answer 에 못 답한 이유가 들어 있다."""

    answer: str
    can_answer: bool = True
    tool_calls: list[dict] = field(default_factory=list)


def _post(body: dict) -> dict:
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": API_VERSION}
    res = httpx.post(API_URL, json=body, headers=headers, timeout=60.0)
    res.raise_for_status()
    return res.json()


def _result_text(data: dict) -> str:
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return json.dumps({"truncated": True, "text": text[:MAX_TOOL_RESULT_CHARS]}, ensure_ascii=False)


def run_agent(
    system: str,
    messages: list[dict],
    tools: list[Tool],
    post: Post | None = None,
    max_steps: int = 4,
    max_tokens: int = 1024,
) -> AgentReply:
    """도구를 최대 max_steps 번 부르며 답을 만든다. 키가 없거나 호출이 실패하면 LLMUnavailable."""
    if post is None:
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았어요")
        post = _post
    by_name = {t.name: t for t in tools}
    messages = list(messages)
    calls_log: list[dict] = []
    try:
        for _ in range(max_steps):
            reply = post(
                {
                    "model": settings.llm_model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "tools": [t.spec() for t in tools],
                    "messages": messages,
                }
            )
            content = reply.get("content") or []
            calls = [c for c in content if c.get("type") == "tool_use"]
            if not calls:
                text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
                if not text.strip():
                    raise LLMUnavailable("AI 응답이 비어 있어요")
                return AgentReply(text.strip(), True, calls_log)
            messages.append({"role": "assistant", "content": content})
            outputs = []
            for call in calls:
                args = call.get("input") or {}
                calls_log.append({"name": call["name"], "input": args})
                try:
                    tool = by_name[call["name"]]
                    data, err = tool.run(args), False
                except (KeyError, ValueError, TypeError, ApiError) as e:
                    data, err = {"error": getattr(e, "message", None) or str(e)}, True
                outputs.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": _result_text(data),
                        "is_error": err,
                    }
                )
            messages.append({"role": "user", "content": outputs})
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise LLMUnavailable(f"AI 호출에 실패했어요 ({type(e).__name__})") from None
    raise LLMUnavailable("AI 가 정해진 횟수 안에 답을 끝내지 못했어요")


def ask_agent(
    system: str, question: str, tools: list[Tool], post: Post | None = None, max_steps: int = 4
) -> AgentReply:
    """run_agent 를 부르되 실패하면 예외 대신 can_answer=False 인 답을 돌려준다(부른 에이전트가 이어서 말하도록)."""
    try:
        return run_agent(
            system, [{"role": "user", "content": question}], tools, post=post, max_steps=max_steps
        )
    except LLMUnavailable as e:
        return AgentReply(f"담당 에이전트가 답하지 못했어요: {e}", can_answer=False)
