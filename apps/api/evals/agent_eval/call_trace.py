"""평가 전용 호출 추적(T35 chat-03 원인 확인용). 모델 호출마다 **상태값만** 남긴다. 운영 코드는 바꾸지 않는다.

측정기(`usage.meter_llm_calls`)가 이미 보는 요청 본문과 응답으로 호출 하나당 한 줄을 만든다:
- 호출한 Agent 역할(`role`): 시스템 프롬프트 글로 가른다(가짜 모델의 `agent_of` 와 같은 방식 + 대화 분석 호출). 추정이 아니라 본문에서 읽은 값이지만, 새 Agent 가 생기면 분류가 `main` 으로 떨어질 수 있다.
- 요청한 `max_tokens`, 응답의 `stop_reason`, 입력·출력 토큰, 응답 블록 종류별 개수와 글자 수(글이 비었는지 알 수 있다).
- 이 호출의 요청 본문에 **처음 실려 온** 도구 결과의 상태: 도구 이름, 오류 여부, 글자 수. 탭 Agent 를 부른 `ask_*` 결과는 `can_answer`,
  못 답한 사유(앱이 쓰는 고정 머리말 뒤의 예외 종류·HTTP 상태만, 최대 `REASON_MAX` 자·스크러버 통과), 잘림 안내 포함 여부를 더한다.

저장하지 않는 것: 질문·답·도구 인자·도구 결과 본문·대화·문서·이름·키. 값을 알 수 없으면 항목을 빼거나 `None` 으로 두고 추측해서 채우지 않는다.
관찰이 평가 동작을 바꾸면 안 되므로 어떤 오류도 호출 쪽으로 올리지 않는다(실패하면 `trace_error` 만 남긴다).
"""

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from app.shared.llm import transport

from .scrub import scrub_text

SCHEMA_VERSION = 1
REASON_MAX = 120
ASK_PREFIX = "담당 에이전트가 답하지 못했어요: "  # `shared/llm/agent.ask_agent` 가 LLMUnavailable 때 쓰는 머리말
ASK_TOOLS = ("ask_billing", "ask_family_chat", "ask_schedule", "ask_care")
OTHER_STRUCTURED = "structured_other"  # 구조화 출력이지만 대화 분석이 아닌 호출(일정 Agent 등)


def role_of(body: Mapping[str, Any]) -> str:
    """요청을 낸 Agent: analysis | structured_other | billing | family_chat | main."""
    from app.features.family_chat.ai_service import ANALYSIS_SYSTEM

    from . import fake_model

    if "output_config" in body:
        return "analysis" if body.get("system") == ANALYSIS_SYSTEM else OTHER_STRUCTURED
    return fake_model.agent_of(body)


def _chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(
            len(str(b.get("text", ""))) if isinstance(b, Mapping) else len(str(b)) for b in content
        )
    return len(json.dumps(content, ensure_ascii=False, default=str))


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(b.get("text", "")) for b in content if isinstance(b, Mapping))
    return ""


def _ask_fields(content: Any) -> dict[str, Any]:
    """`ask_*` 도구 결과(JSON 글)에서 상태만 읽는다: can_answer, 못 답한 사유, 잘림 안내 여부. 읽을 수 없으면 `can_answer` 를 None 으로 둔다."""
    from app.shared.llm.tool_graph import TRUNCATED_NOTE

    try:
        data = json.loads(_text_of(content))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"can_answer": None}
    can = data.get("can_answer")
    out: dict[str, Any] = {"can_answer": can if isinstance(can, bool) else None}
    answer = data.get("answer")
    if isinstance(answer, str):
        out["answer_chars"] = len(answer)
        out["truncated_note"] = TRUNCATED_NOTE.strip() in answer
        if can is False:
            if answer.startswith(ASK_PREFIX):  # 앱의 고정 머리말 뒤(예외 종류·HTTP 상태)만 남긴다
                out["fallback_reason"] = scrub_text(answer[len(ASK_PREFIX) :])[:REASON_MAX]
            else:
                out["fallback_reason"] = None  # 알려진 머리말이 아니면 글을 남기지 않는다
    return out


class CallTracer:
    """한 사례·반복 안의 호출을 순서대로 모은다(측정기가 호출 직후 `observe` 를 부른다)."""

    def __init__(self, case_id: str, repeat: int) -> None:
        self.case_id = case_id
        self.repeat = repeat
        self.rows: list[dict[str, Any]] = []
        self._tool_names: dict[str, str] = {}  # tool_use id -> 도구 이름
        self._seen: set[str] = set()  # 이미 기록한 tool_result id(본문마다 앞 결과가 다시 실린다)

    def observe(
        self, body: Mapping[str, Any], payload: Any, error: BaseException | None = None
    ) -> None:
        index = len(self.rows)
        try:
            self.rows.append(self._row(index, body, payload, error))
        except Exception as e:  # noqa: BLE001  관찰이 평가를 바꾸면 안 된다
            self.rows.append(
                {
                    "case_id": self.case_id,
                    "repeat": self.repeat,
                    "call_index": index,
                    "trace_error": type(e).__name__,
                }
            )

    def _row(
        self, index: int, body: Mapping[str, Any], payload: Any, error: BaseException | None
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "case_id": self.case_id,
            "repeat": self.repeat,
            "call_index": index,
            "role": role_of(body),
            "model": body.get("model"),
            "max_tokens": body.get("max_tokens"),
            "ok": error is None,
        }
        results = self._new_results(body)
        if results:
            row["tool_results"] = results
        if error is not None:
            row["error_type"] = type(error).__name__
            return row
        if not isinstance(payload, Mapping):
            row["ok"] = False
            return row
        tokens_in, tokens_out = transport.usage_of(dict(payload))
        content = payload.get("content")
        blocks = content if isinstance(content, list) else []
        kinds = Counter(str(b.get("type")) for b in blocks if isinstance(b, Mapping))
        text_chars = sum(
            len(str(b.get("text", "")))
            for b in blocks
            if isinstance(b, Mapping) and b.get("type") == "text"
        )
        requested = []
        for b in blocks:
            if isinstance(b, Mapping) and b.get("type") == "tool_use":
                name = str(b.get("name"))
                requested.append(name)
                if b.get("id") is not None:
                    self._tool_names[str(b["id"])] = name
        row.update(
            stop_reason=payload.get("stop_reason"),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_blocks=dict(sorted(kinds.items())),
            text_chars=text_chars,
            requested_tools=requested,
        )
        if payload.get("model"):
            row["model"] = payload.get("model")
        return row

    def _new_results(self, body: Mapping[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for message in body.get("messages") or []:
            content = message.get("content") if isinstance(message, Mapping) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, Mapping) and block.get("type") == "tool_result"):
                    continue
                use_id = str(block.get("tool_use_id"))
                if use_id in self._seen:
                    continue
                self._seen.add(use_id)
                tool = self._tool_names.get(
                    use_id
                )  # 이 측정기가 못 본 호출이면 None(추측하지 않는다)
                entry: dict[str, Any] = {
                    "tool": tool,
                    "is_error": bool(block.get("is_error", False)),
                    "chars": _chars(block.get("content")),
                }
                if tool in ASK_TOOLS:
                    entry.update(_ask_fields(block.get("content")))
                out.append(entry)
        return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """호출 줄들의 집계: 역할별 호출 수, stop_reason 별 수, 길이 상한에 걸린 호출, 도구 오류, 탭 Agent 가 못 답한 수."""
    ok_rows = [r for r in rows if "trace_error" not in r]
    answered = [r for r in ok_rows if r.get("ok") and "stop_reason" in r]  # 응답을 받은 호출
    results = [t for r in ok_rows for t in r.get("tool_results", [])]
    return {
        "calls": len(rows),
        "calls_by_role": dict(sorted(Counter(r.get("role") for r in ok_rows).items())),
        "stop_reasons": dict(sorted(Counter(str(r.get("stop_reason")) for r in answered).items())),
        "max_tokens_hits": sum(1 for r in answered if r.get("stop_reason") == "max_tokens"),
        # 글도 도구 요청도 없는 응답(도구만 요청한 정상 호출은 세지 않는다)
        "calls_without_text": sum(
            1 for r in answered if not r.get("text_chars") and not r.get("requested_tools")
        ),
        "calls_failed": sum(1 for r in ok_rows if not r.get("ok")),
        "tool_result_errors": sum(1 for t in results if t.get("is_error")),
        "ask_results_cannot_answer": sum(1 for t in results if t.get("can_answer") is False),
        "trace_errors": len(rows) - len(ok_rows),
    }


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "note": "상태값만 기록한다(질문·답·도구 인자·결과 본문·대화·이름·키 없음). role 은 시스템 프롬프트 글로 가른 값이다.",
        "summary": summarize(rows),
        "calls": rows,
    }
