"""AI(Anthropic) 호출 래퍼. 기능 코드는 SDK 를 직접 부르지 않고 여기만 쓴다.

키가 없거나 호출이 실패하면 LLMUnavailable 을 내고, 호출한 쪽이 대체 동작(규칙 기반 답)을 쓴다.
TODO: 사용자별 하루 호출 한도, 이미지 입력 — 원본 프로젝트의 common/gabi_llm.py 를 참고한다.
"""

import httpx

from app.shared.config import settings

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class LLMUnavailable(Exception):
    pass


def available() -> bool:
    return bool(settings.anthropic_api_key)


def complete(
    prompt: str, system: str | None = None, max_tokens: int = 1024, timeout: float = 30.0
) -> str:
    if not available():
        raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았어요")
    body: dict = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": API_VERSION}
    try:
        res = httpx.post(API_URL, json=body, headers=headers, timeout=timeout)
        res.raise_for_status()
        parts = res.json().get("content") or []
    except (httpx.HTTPError, ValueError) as e:
        raise LLMUnavailable(f"AI 호출에 실패했어요 ({type(e).__name__})") from None
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    if not text:
        raise LLMUnavailable("AI 응답이 비어 있어요")
    return text
