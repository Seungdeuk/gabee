"""결과 파일에 섞일 수 있는 개인정보 형태를 지운다.

새 정규식을 만들지 않고 기존 개인정보 탐지기(`app.shared.privacy.detectors`)의 정규식을 재사용한다.
평가 데이터는 합성이지만, 모델 답이 전화번호·이메일 같은 형태를 지어낼 수 있어서 저장 직전에 한 번 더 지운다.
"""

from typing import Any

from app.shared.privacy.detectors import CARD_RE, EMAIL_RE, PHONE_RE, RRN_RE

# 긴 숫자 형태를 먼저 지운다(주민번호·카드번호가 전화번호 규칙에 일부 걸리지 않게)
_RULES = (
    (RRN_RE, "[주민번호]"),
    (CARD_RE, "[카드번호]"),
    (EMAIL_RE, "[이메일]"),
    (PHONE_RE, "[전화번호]"),
)


def scrub_text(text: str) -> str:
    for pattern, token in _RULES:
        text = pattern.sub(token, text)
    return text


def scrub_value(value: Any) -> Any:
    """문자열, 딕셔너리(키 포함), 목록 안쪽까지 재귀로 지운다. 그 밖의 값은 그대로 둔다."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {scrub_text(str(k)): scrub_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub_value(v) for v in value]
    return value
