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


# 점검 뒤에 이어서 할 일(후속 작업). 규칙과 달리 기록을 남기는 다른 일을 한다(예: 관리자 초안 만들기).
# 알림 점검(admin_alerts)이 규칙을 모두 돌리고 저장한 뒤에 부른다. 하나가 실패해도 다른 후속 작업과 점검 결과에는 영향이 없다.
FollowUp = Callable[[Session, datetime], None]

_FOLLOWUPS: dict[str, FollowUp] = {}


def register_followup(name: str, run: FollowUp) -> None:
    """같은 이름으로 다시 올리면 바꾼다."""
    _FOLLOWUPS[name] = run


def all_followups() -> list[tuple[str, FollowUp]]:
    return sorted(_FOLLOWUPS.items(), key=lambda item: item[0])
