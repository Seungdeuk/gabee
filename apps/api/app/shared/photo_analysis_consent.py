"""가족 사진 이미지 분석의 동의 조건(ADR 0020: ① 서버 스위치 ② 가족 활성화 ③ 올린 사람의 동의 + 사진별 AI 분석 제외)을
다른 기능이 `family_memory` 내부를 import 하지 않고 확인하는 통로(`memory_hooks`·`chat_library` 와 같은 등록식).

- `family_memory` 가 확인 함수를 등록한다. 등록되지 않았거나(기능 없음·시험) 확인이 실패하면 **아무 사진도 허용하지 않는다**(fail-closed).
- 이 통로는 3중 조건·소급 동의(동의 전에 올린 사진은 소급 동의가 있어야 한다)·분석 제외만 본다. 어떤 판별 상태(`photo`·`unsure`)의 사진을 분석·노출할지는 부르는 쪽 정책이 따로 정한다(ADR 0021·0026).
- 사진 내용·경로는 다루지 않고 로그에는 오류 종류만 남긴다."""

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# (db, group_id, {첨부 id: (올린 사람 id, 올린 시각)}) -> 분석해도 되는 첨부 id 집합
Checker = Callable[[Session, str, dict[str, tuple[str, datetime]]], set[str]]
_checker: Checker | None = None


def register(fn: Checker) -> None:
    global _checker
    _checker = fn


def allowed_photos(
    db: Session, group_id: str, uploaders: dict[str, tuple[str, datetime]]
) -> set[str]:
    """분석해도 되는 첨부 id 만(요청한 것 중에서만). 확인할 수 없으면 빈 집합."""
    if not uploaders or _checker is None:
        return set()
    try:
        return set(_checker(db, group_id, dict(uploaders))) & set(uploaders)
    except Exception as exc:  # noqa: BLE001  확인 실패는 막는 쪽으로
        logger.warning("photo analysis consent check failed error=%s", type(exc).__name__)
        return set()
