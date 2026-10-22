"""knowledge 기능을 시험하기 위한 채팅: LLM 이 검색 함수를 불러 기록을 근거로 답한다.

LLM 은 `tools.TOOL_SPECS` 의 함수만 부를 수 있고, 어느 가족 그룹의 기록을 볼지는 서버가 정한다(LLM 이 고르지 못한다).
키가 없거나 호출이 실패하면 LLM 없이 검색 결과만 보여 준다. 공용 `shared/llm` 은 건드리지 않고 같은 설정을 쓴다."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm.client import API_URL, API_VERSION

from . import tools

SYSTEM_PROMPT = (
    "당신은 가족 비서 '가비'입니다. 가족이 저장한 기록(고지서, 영수증, 병원 내역, 증명서 등)에 대한 질문은 "
    "반드시 search_knowledge 로 먼저 찾아보고, 찾은 기록만 근거로 짧고 따뜻한 한국어로 답하세요. "
    "질문 낱말로 못 찾으면 다른 낱말(예: 비행기→항공권)로 한 번 더 찾아보세요. "
    "근거가 없으면 지어내지 말고 찾지 못했다고 말하세요. 답에는 기록 제목을 함께 알려 주세요. "
    "has_unread_parts 가 true 인 기록은 원본에서 읽지 못한 부분이 있으니 값을 단정하지 말고 확인을 권하세요. "
    "sensitive 가 true 인 기록(가족관계, 병원 등)은 필요한 만큼만 말하세요. 의료 진단은 하지 않습니다."
)
MAX_STEPS = 4

Post = Callable[[dict], dict]


@dataclass
class AskResult:
    answer: str
    source: str  # ai | fallback
    sources: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)


def _post(body: dict) -> dict:
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": API_VERSION}
    res = httpx.post(API_URL, json=body, headers=headers, timeout=60.0)
    res.raise_for_status()
    return res.json()


def _run_tool(db: Session, group_id: str, name: str, args: dict) -> dict:
    if name == "search_knowledge":
        allowed = {"query", "top_k", "kind_label", "date_from", "date_to"}
        return tools.search_knowledge(
            db, group_id, **{k: v for k, v in args.items() if k in allowed}
        )
    if name == "get_item":
        return tools.get_item(db, group_id, str(args.get("item_id", "")))
    if name == "list_items":
        allowed = {"kind_label", "limit"}
        return tools.list_items(db, group_id, **{k: v for k, v in args.items() if k in allowed})
    raise ValueError(f"알 수 없는 함수: {name}")


def _source(result: dict) -> dict:
    return {
        "item_id": result["item_id"],
        "title": result["title"],
        "kind_label": result["kind_label"],
        "page": result.get("page"),
        "source_path": result.get("source_path"),
        "date": result.get("date"),
    }


def _fallback(db: Session, group_id: str, question: str) -> AskResult:
    found = tools.search_knowledge(db, group_id, question, top_k=3)["results"]
    if not found:
        return AskResult("AI 연결이 꺼져 있고, 관련 기록도 찾지 못했어요.", "fallback")
    lines = [f"- {r['title']} ({r['kind_label']})" for r in found]
    return AskResult(
        "AI 연결이 꺼져 있어서 찾은 기록만 보여드려요.\n" + "\n".join(lines),
        "fallback",
        [_source(r) for r in found],
    )


def _messages(question: str, history: list[dict] | None) -> list[dict]:
    """앞 대화를 LLM 형식으로 바꾼다(user 로 시작하고 user/assistant 가 번갈아 나오게 맞춘다)."""
    out: list[dict] = []
    for turn in (history or [])[-10:]:
        role, text = turn["role"], turn["text"].strip()
        if not text or (not out and role != "user"):
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    if out and out[-1]["role"] == "user":
        out[-1]["content"] += "\n" + question
    else:
        out.append({"role": "user", "content": question})
    return out


def ask(
    db: Session,
    group_id: str,
    question: str,
    post: Post | None = None,
    history: list[dict] | None = None,
) -> AskResult:
    """질문 하나에 답한다. `post` 는 테스트에서 가짜 LLM 을 끼우는 자리다."""
    if post is None:
        if not settings.anthropic_api_key:
            return _fallback(db, group_id, question)
        post = _post
    messages = _messages(question, history)
    result = AskResult("", "ai")
    seen: set[str] = set()
    try:
        for _ in range(MAX_STEPS):
            reply = post(
                {
                    "model": settings.llm_model,
                    "max_tokens": 1024,
                    "system": SYSTEM_PROMPT,
                    "tools": tools.TOOL_SPECS,
                    "messages": messages,
                }
            )
            content = reply.get("content") or []
            calls = [c for c in content if c.get("type") == "tool_use"]
            if not calls:
                result.answer = "".join(
                    c.get("text", "") for c in content if c.get("type") == "text"
                ).strip()
                break
            messages.append({"role": "assistant", "content": content})
            outputs = []
            for call in calls:
                args = call.get("input") or {}
                result.tool_calls.append({"name": call["name"], "input": args})
                try:
                    data = _run_tool(db, group_id, call["name"], args)
                    err = False
                except (ValueError, ApiError, TypeError) as e:
                    data, err = {"error": str(e)}, True
                for r in data.get("results", []) + ([data] if "item_id" in data else []):
                    if r["item_id"] not in seen:
                        seen.add(r["item_id"])
                        result.sources.append(_source(r))
                outputs.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(data, ensure_ascii=False),
                        "is_error": err,
                    }
                )
            messages.append({"role": "user", "content": outputs})
    except (httpx.HTTPError, ValueError, KeyError):
        return _fallback(db, group_id, question)
    if not result.answer:
        return _fallback(db, group_id, question)
    # 검색에 걸렸어도 답에 쓰지 않은 기록은 출처에서 뺀다(제목이 답에 나온 것만). 하나도 없으면 전부 둔다.
    used = [s for s in result.sources if s["title"] in result.answer]
    if used:
        result.sources = used
    return result
