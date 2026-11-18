"""관리자 알림 규칙 명단. 각 기능이 자기 폴더의 alert_rules.py 에서 register() 로 규칙을 올린다.

규칙은 숫자만 읽어 `Finding` 목록을 돌려준다. 문구(message)에는 개수·비율·오류 종류만 담고,
이름·이메일·사용자 id·오류 본문은 넣지 않는다. 감시는 AI 없이 숫자 비교로만 한다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Finding:
    key: str  # 고유 키(규칙 이름 + 구간). 같은 키는 기록표에 한 번만 들어간다
    rule: str  # 규칙 이름
    severity: str  # "긴급" | "주의" | "보통"
    message: str  # 숫자만 든 문구
    menu: str  # 확인할 메뉴 이름


RuleCheck = Callable[[Session, datetime], list[Finding]]

_RULES: dict[str, RuleCheck] = {}


def register(name: str, check: RuleCheck) -> None:
    """같은 이름으로 다시 올리면 바꾼다(모듈을 다시 읽어도 두 번 들어가지 않는다)."""
    _RULES[name] = check


def all_rules() -> list[tuple[str, RuleCheck]]:
    return sorted(_RULES.items(), key=lambda item: item[0])
