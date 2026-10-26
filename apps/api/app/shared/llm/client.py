"""AI(Anthropic) 호출 래퍼. 기능 코드는 SDK 를 직접 부르지 않고 여기만 쓴다.

키가 없거나 호출이 실패하면 LLMUnavailable 을 내고, 호출한 쪽이 대체 동작(규칙 기반 답)을 쓴다.
- `complete`: 글자 답(AI 채팅 등). `model` 을 주면 그 모델로, 안 주면 설정값(`llm_model`)으로 부른다(`complete_json` 도 같다).
- `complete_json`: 구조화 출력(Structured Outputs, `output_config.format` json_schema)으로 검증 가능한 JSON 을 받고, 입력·출력 토큰 수도 돌려준다.
호출은 한 번만 한다(실패해도 여기서 다시 시도하지 않는다 — 비용·한도는 호출한 쪽(ai_guard)이 관리한다).
TODO: 이미지 입력 — 원본 프로젝트의 common/gabi_llm.py 를 참고한다.
"""

import json
from dataclasses import dataclass

import httpx

from app.shared.config import settings

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class LLMUnavailable(Exception):
    pass


@dataclass(frozen=True)
class JsonResult:
    data: dict
    input_tokens: int
    output_tokens: int
    model: str


def available() -> bool:
    return bool(settings.anthropic_api_key)


def _headers() -> dict[str, str]:
    return {"x-api-key": settings.anthropic_api_key, "anthropic-version": API_VERSION}


def _post(body: dict, timeout: float) -> dict:
    try:
        res = httpx.post(API_URL, json=body, headers=_headers(), timeout=timeout)
        res.raise_for_status()
        return res.json()
    except (
        httpx.HTTPError,
        ValueError,
    ) as e:  # 오류 문구에는 종류만(요청·응답 본문·키는 넣지 않는다)
        raise LLMUnavailable(f"AI 호출에 실패했어요 ({type(e).__name__})") from None


def _text(payload: dict) -> str:
    parts = payload.get("content") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()


def complete(
    prompt: str,
    system: str | None = None,
    max_tokens: int = 1024,
    timeout: float = 30.0,
    model: str | None = None,
) -> str:
    if not available():
        raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았어요")
    body: dict = {
        "model": model or settings.llm_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    text = _text(_post(body, timeout))
    if not text:
        raise LLMUnavailable("AI 응답이 비어 있어요")
    return text


def complete_json(
    prompt: str,
    schema: dict,
    system: str | None = None,
    max_tokens: int | None = None,
    timeout: float = 40.0,
    model: str | None = None,
) -> JsonResult:
    """구조화 출력으로 schema 에 맞는 JSON 을 받는다(한 번만 호출). 잘렸거나 거절됐거나 JSON 이 아니면 LLMUnavailable."""
    if not available():
        raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았어요")
    body: dict = {
        "model": model or settings.llm_model,
        "max_tokens": max_tokens or settings.anthropic_max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "output_config": {
            "format": {"type": "json_schema", "schema": schema},
            "effort": settings.ai_effort,
        },
    }
    if system:
        body["system"] = system
    payload = _post(body, timeout)
    if payload.get("stop_reason") in ("max_tokens", "refusal"):
        raise LLMUnavailable(f"AI 응답을 쓸 수 없어요 ({payload.get('stop_reason')})")
    try:
        data = json.loads(_text(payload))
    except ValueError:
        raise LLMUnavailable("AI 응답이 JSON 이 아니에요") from None
    if not isinstance(data, dict):
        raise LLMUnavailable("AI 응답 형식이 올바르지 않아요")
    usage = payload.get("usage") or {}
    return JsonResult(
        data=data,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        model=str(payload.get("model") or model or settings.llm_model),
    )
