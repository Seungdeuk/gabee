"""가명화 파이프라인의 공통 타입: 개인정보 종류(Kind), 위험도(Risk), 탐지 구간(Span).

이 패키지는 외부 라이브러리 없이 표준 라이브러리만 쓴다. 탐지는 정규식과 검증 규칙이라 **완전하지 않다**
(한국어 이름·주소는 놓칠 수 있다). 마스킹이 완전한 보호를 보장한다고 보지 않는다.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    """개인정보 종류. 값(문자열)은 JSON·통계의 키로 그대로 쓴다."""

    PHONE = "PHONE"
    EMAIL = "EMAIL"
    RRN = "RRN"  # 주민등록번호·외국인등록번호
    CARD = "CARD"
    ACCOUNT = "ACCOUNT"
    SECRET = "SECRET"  # 비밀번호·인증번호 같은 비밀 값
    ADDRESS = "ADDRESS"
    PERSON = "PERSON"


class Risk(StrEnum):
    """위험도. 겹치는 탐지 결과를 정리할 때 HIGH 가 먼저 남는다."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


RISK_BY_KIND: dict[Kind, Risk] = {
    Kind.RRN: Risk.HIGH,
    Kind.CARD: Risk.HIGH,
    Kind.SECRET: Risk.HIGH,
    Kind.ACCOUNT: Risk.HIGH,
    Kind.PHONE: Risk.MEDIUM,
    Kind.EMAIL: Risk.MEDIUM,
    Kind.ADDRESS: Risk.MEDIUM,
    Kind.PERSON: Risk.LOW,
}

RISK_RANK: dict[Risk, int] = {Risk.HIGH: 0, Risk.MEDIUM: 1, Risk.LOW: 2}


@dataclass(frozen=True)
class Span:
    """원문에서 개인정보로 본 구간 [start, end).

    score 는 0~1 의 확신 정도(규칙 기반 추정값이며 확률이 아니다). source 는 어떤 규칙이 찾았는지(디버깅용 짧은 이름).
    canonical 은 같은 사람·값을 한 토큰으로 묶을 때 쓰는 대표 값이다(예: 이름 사전에서 '민수' -> '김민수').
    """

    kind: Kind
    start: int
    end: int
    score: float
    source: str
    canonical: str | None = field(default=None, repr=False)

    @property
    def risk(self) -> Risk:
        return RISK_BY_KIND[self.kind]

    @property
    def length(self) -> int:
        return self.end - self.start
