"""로컬 언어 모델(Ollama) 호출 래퍼. 글자가 서버 밖으로 나가지 않아야 할 때 client.complete 대신 쓴다.

Ollama 가 꺼져 있거나 응답이 깨지면 LLMUnavailable 을 내고, 호출한 쪽이 대체 동작을 쓴다.
"""

import json

import httpx

from app.shared.config import settings

from .client import LLMUnavailable


def complete_json(prompt: str, system: str | None = None, timeout: float | None = None) -> dict:
    """JSON 객체 하나로 답하게 하고 dict 로 돌려준다(Ollama format=json)."""
    messages = [{"role": "user", "content": prompt}]
    if system:
        messages.insert(0, {"role": "system", "content": system})
    body = {
        "model": settings.local_llm_model,
        "messages": messages,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        res = httpx.post(
            f"{settings.local_llm_url.rstrip('/')}/api/chat",
            json=body,
            timeout=timeout or settings.local_llm_timeout,
        )
        res.raise_for_status()
        data = json.loads(res.json()["message"]["content"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        raise LLMUnavailable(f"로컬 AI 호출에 실패했어요 ({type(e).__name__})") from None
    if not isinstance(data, dict):
        raise LLMUnavailable("로컬 AI 응답이 JSON 객체가 아니에요")
    return data
