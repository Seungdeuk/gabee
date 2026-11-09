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
from app.shared.privacy.ner import PrivacyUnavailable

from . import tool_graph, transport
from .chat_model import PostChatModel, to_langchain_messages
from .transport import LLMUnavailable

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
    proposals: list = field(
        default_factory=list
    )  # proposals.Proposal: 사용자 확인을 기다리는 쓰기 제안
    # 앱이 확인 카드로 보여 줄 실행 정보(예: 일정 공유 등록·수정·삭제). 사용자가 버튼을 눌러야 실행되고, 서버는 돌려받은 값을 다시 검증한다
    confirmations: list[dict] = field(default_factory=list)
    user_text: str = ""  # answer 에 메인에게 주는 안내가 섞이는 에이전트가 사용자에게 줄 글을 따로 줄 때(직통 응답에 쓴다)
    input_tokens: int = 0  # 이 답을 만들며 쓴 토큰 합(여러 번 부른 호출의 합, 사용 기록용)
    output_tokens: int = 0
    model: str = ""
    calls: int = 0  # 모델을 실제로 부른 횟수(관문의 사용 기록·한도에 센다)


def _post(body: dict) -> dict:
    """탭 에이전트의 호출: 429·5xx·연결 실패는 한 번 더 시도한다(시험은 이 이름을 가짜로 바꾼다)."""
    return transport.post_messages(body, timeout=60.0, retry=True)


def _status_detail(res: httpx.Response) -> str:
    """HTTP 상태 코드와 API 가 준 오류 종류·메시지(요청에 쓴 키는 응답에 없다). 크레딧 부족 같은 원인을 알 수 있게 한다."""
    try:
        err = res.json().get("error") or {}
        return f"HTTP {res.status_code} {err.get('type', '')}: {err.get('message', '')}".strip()
    except ValueError:
        return f"HTTP {res.status_code}"


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
    """도구를 최대 max_steps 번 부르며 답을 만든다. 키가 없거나 호출이 실패하면 LLMUnavailable.

    반복 흐름은 메인 채팅과 같은 `tool_graph`(랭그래프)가 돌리고, 여기서는 탭 에이전트만의 규칙을 더한다:
    다시 시도하는 기본 `_post`, 도구 결과 길이 제한, 개인정보 엔진 오류 통과, 오류의 LLMUnavailable 변환."""
    if post is None:
        if not settings.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았어요")
        post = _post
    by_name = {t.name: t for t in tools}
    calls_log: list[dict] = []
    used = [0, 0]  # 입력·출력 토큰 합

    def counting(body: dict) -> dict:
        reply = post(body)
        used_in, used_out = transport.usage_of(reply)
        used[0] += used_in
        used[1] += used_out
        return reply

    def handle(calls: list[dict]) -> tool_graph.ToolRound:
        outputs: list[tuple[str, str, bool]] = []
        for call in calls:
            args = call.get("args") or {}
            calls_log.append({"name": call["name"], "input": args})
            try:
                tool = by_name[call["name"]]
                data, err = tool.run(args), False
            except PrivacyUnavailable:
                raise  # 개인정보 보호 엔진을 못 쓰면(required) 도구 오류로 숨기지 않고 503 으로 끝낸다
            except (KeyError, ValueError, TypeError, ApiError) as e:
                data, err = {"error": getattr(e, "message", None) or str(e)}, True
            outputs.append((call["id"], _result_text(data), err))
        return tool_graph.ToolRound(outputs)

    run = tool_graph.Run(
        model=PostChatModel(
            post=counting,
            llm_model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            tools=[t.spec() for t in tools],
        ),
        handle=handle,
        max_steps=max_steps,
    )
    try:
        if max_steps > 0:  # 0 번이면 모델을 한 번도 부르지 않고 끝난다
            tool_graph.run_graph(run, to_langchain_messages(messages))
    except httpx.HTTPStatusError as e:
        raise LLMUnavailable(f"AI 호출에 실패했어요 ({_status_detail(e.response)})") from None
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise LLMUnavailable(f"AI 호출에 실패했어요 ({type(e).__name__})") from None
    if not run.finished:
        raise LLMUnavailable("AI 가 정해진 횟수 안에 답을 끝내지 못했어요")
    if not run.answer:
        raise LLMUnavailable("AI 응답이 비어 있어요")
    return AgentReply(
        run.answer,
        True,
        calls_log,
        input_tokens=used[0],
        output_tokens=used[1],
        model=settings.llm_model,
        calls=run.steps,
    )


def build_messages(question: str, history: list[dict] | None) -> list[dict]:
    """앞 대화를 LLM 형식으로 바꾼다(user 로 시작하고 user/assistant 가 번갈아 나오게 맞춘다)."""
    out: list[dict] = []
    for turn in (history or [])[-10:]:
        role, text = turn["role"], turn["text"].strip()
        if not text or (not out and role != "user"):
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += chr(10) + text
        else:
            out.append({"role": role, "content": text})
    if out and out[-1]["role"] == "user":
        out[-1]["content"] += chr(10) + question
    else:
        out.append({"role": "user", "content": question})
    return out


def ask_agent(
    system: str,
    question: str,
    tools: list[Tool],
    post: Post | None = None,
    max_steps: int = 4,
    history: list[dict] | None = None,
    proposals: list | None = None,
) -> AgentReply:
    """run_agent 를 부르되 실패하면 예외 대신 can_answer=False 인 답을 돌려준다(부른 에이전트가 이어서 말하도록)."""
    try:
        reply = run_agent(
            system, build_messages(question, history), tools, post=post, max_steps=max_steps
        )
        reply.proposals = list(proposals or [])
        return reply
    except LLMUnavailable as e:
        return AgentReply(f"담당 에이전트가 답하지 못했어요: {e}", can_answer=False)
