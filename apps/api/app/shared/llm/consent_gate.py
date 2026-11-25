"""가족 채팅방 자동 처리(채팅 문서·사진의 문서함 등록)의 외부 AI 전송 관문.

- 가족 채팅 목적의 처리는 `family_chat(group_id)` 범위 안에서 돈다(`library.register_chat_*`). 이 범위 안에서 외부로 나가는 호출
  (Anthropic: `transport.post_messages`, Jev: `jev.ask`)은 **보내기 직전마다** 가족 AI 동의를 다시 읽는다. 동의가 없으면 보내지 않고
  `ConsentRequired` 를 낸다(처리 도중 동의를 꺼도 그 뒤의 호출은 나가지 않는다). 이미 나간 호출은 되돌릴 수 없다.
- 한 번이라도 막히면 범위에 `blocked` 가 남는다. 저장하는 쪽(`files._process_once`)은 이것을 보고 **로컬 규칙으로 대신 처리한 결과를 등록하지 않는다**
  (외부 호출 실패를 로컬 가리기로 대신하면 이름·주소가 남은 문서가 문서함에 들어가기 때문이다).
- 범위 밖(메인 AI 직접 업로드 `/ai-assistant/files`, @가비·메인 채팅 등)은 이 관문을 거치지 않는다(기존 정책 유지).
- 동의를 읽지 못하면(DB 오류) 막는다(fail-closed). 스레드 풀로 나눠 부르는 곳은 `carry` 로 범위를 넘긴다(contextvar 는 새 스레드로 이어지지 않는다).
사진·글 내용은 로그에 남기지 않는다."""

import contextvars
import logging
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

from .transport import LLMUnavailable

logger = logging.getLogger(__name__)


class ConsentRequired(LLMUnavailable):
    """가족 채팅 목적의 처리인데 가족 AI 동의가 없어 외부로 보내지 않았다."""


@dataclass
class _Scope:
    group_id: str
    blocked: bool = False


_scope: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar(
    "family_chat_consent_scope", default=None
)


def family_ai_allowed(group_id: str) -> bool:
    """가족 AI 동의가 지금 켜져 있는가(못 읽으면 False: 막는 쪽). 가족 채팅 목적의 외부 전송 판단은 모두 이 함수로 한다."""
    try:
        from app.shared import ai_guard
        from app.shared.db import SessionLocal

        with SessionLocal() as db:
            return ai_guard.is_enabled(db, group_id)
    except Exception as exc:  # noqa: BLE001  종류만 남긴다
        logger.warning("family chat consent check failed error=%s", type(exc).__name__)
        return False


@contextmanager
def family_chat(group_id: str):
    """가족 채팅 목적의 처리 범위. 범위 안의 외부 호출은 동의를 확인한다."""
    scope = _Scope(group_id)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


def allowed_now() -> bool:
    """범위 밖이면 True(관문 없음). 범위 안이면 동의를 지금 다시 읽고, 없으면 범위를 막힘으로 표시한다."""
    scope = _scope.get()
    if scope is None:
        return True
    if scope.blocked:
        return False  # 한 번 막힌 처리는 끝까지 막는다(중간에 다시 켜져도 이미 로컬로 대신한 단계가 있을 수 있다)
    if family_ai_allowed(scope.group_id):
        return True
    scope.blocked = True
    return False


def check() -> None:
    """외부로 보내기 직전에 부른다. 범위 안이고 동의가 없으면 `ConsentRequired`."""
    if not allowed_now():
        raise ConsentRequired("가족 AI 동의가 없어 외부로 보내지 않았어요")


def blocked() -> bool:
    """이 처리에서 동의 때문에 막힌 외부 호출이 있었는가(있으면 결과를 등록하지 않는다)."""
    scope = _scope.get()
    return bool(scope and scope.blocked)


def carry(fn: Callable) -> Callable:
    """지금 범위를 스레드 풀 작업으로 넘기는 래퍼(범위 밖이면 그대로 둔다)."""
    scope = _scope.get()
    if scope is None:
        return fn

    def run(*args, **kwargs):
        token = _scope.set(scope)
        try:
            return fn(*args, **kwargs)
        finally:
            _scope.reset(token)

    return run
