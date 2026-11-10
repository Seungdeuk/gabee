"""Anthropic Messages API 를 부르는 유일한 곳(HTTP 호출은 여기 한 군데뿐이다).

`client`(글 답·구조화 출력), `agent`(탭 에이전트 도구 루프), `knowledge/rag_chat`(메인 채팅 도구 루프)가 모두 이 함수를 거친다.
호출 방식(제한 시간·재시도)은 호출한 쪽이 인자로 고르고, 재시도 규칙(어떤 응답을 다시 시도하는지, 얼마나 기다리는지)은
아래 상수에 한 번만 둔다. 기능 코드는 SDK 나 httpx 를 직접 부르지 않는다.

실패는 httpx 예외(`HTTPStatusError`·`ConnectError`·`TimeoutException`)나 `ValueError`(응답이 JSON 이 아님)로 그대로 낸다.
오류를 사용자에게 어떻게 보일지(대체 답, 503 등)는 호출한 쪽이 정한다."""

import time

import httpx

from app.shared.config import settings

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
# 잠깐 뒤 다시 하면 될 수 있는 응답(529 는 Anthropic 과부하)
RETRY_STATUS = {429, 500, 502, 503, 504, 529}
RETRY_WAIT_SECONDS = 1.0


class LLMUnavailable(Exception):
    """키가 없거나 호출이 실패해 AI 를 쓸 수 없다. 호출한 쪽이 대체 동작(규칙 기반 답 등)을 쓴다."""


def headers() -> dict[str, str]:
    return {"x-api-key": settings.anthropic_api_key, "anthropic-version": API_VERSION}


def post_messages(body: dict, *, timeout: float = 60.0, retry: bool = False) -> dict:
    """Messages API 를 부르고 응답 JSON 을 돌려준다.

    retry=True 면 429·5xx 응답이나 연결·시간 초과일 때 잠깐 기다렸다가 한 번만 더 부른다. 그 밖의 오류(4xx 등)는 다시 하지 않는다.
    retry=False(기본)는 한 번만 부른다: 호출 수를 한도에 세는 쪽(`ai_guard`)이 비용을 관리하므로 몰래 다시 부르지 않는다."""
    attempts = 2 if retry else 1
    for attempt in range(1, attempts + 1):
        try:
            res = httpx.post(API_URL, json=body, headers=headers(), timeout=timeout)
            if attempt < attempts and res.status_code in RETRY_STATUS:
                time.sleep(RETRY_WAIT_SECONDS)
                continue
            res.raise_for_status()
            return res.json()
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt == attempts:
                raise
            time.sleep(RETRY_WAIT_SECONDS)
    raise AssertionError("unreachable")  # 마지막 시도는 반환하거나 예외를 던진다


def usage_of(reply: dict) -> tuple[int, int]:
    """응답의 (입력 토큰, 출력 토큰). 사용량이 없으면 0, 0."""
    usage = reply.get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
