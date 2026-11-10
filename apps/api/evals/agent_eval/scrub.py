"""결과 파일에 섞일 수 있는 개인정보 형태를 지운다.

새 정규식을 만들지 않고 기존 개인정보 탐지기(`app.shared.privacy.detectors.detect`)를 재사용한다. 이 탐지기는
전각 숫자·대시 변형과 폭 없는 문자를 정규화한 뒤 찾고, 위치는 원문 기준으로 돌려준다.
평가 데이터는 합성이지만, 모델 답이 전화번호·이메일 같은 형태를 지어낼 수 있어서 저장 직전에 한 번 더 지운다.
합성 이름·주소는 평가 내용이므로 지우지 않고, 번호·계정 같은 식별자 종류만 지운다.
"""

from typing import Any

from app.shared.privacy.detectors import detect
from app.shared.privacy.types import Kind

_TOKENS = {
    Kind.PHONE: "[전화번호]",
    Kind.EMAIL: "[이메일]",
    Kind.RRN: "[주민번호]",
    Kind.CARD: "[카드번호]",
    Kind.ACCOUNT: "[계좌번호]",
    Kind.SECRET: "[비밀값]",
}


def scrub_text(text: str) -> str:
    spans = [s for s in detect(text) if s.kind in _TOKENS]
    for s in sorted(
        spans, key=lambda s: s.start, reverse=True
    ):  # 뒤에서부터 바꿔 앞 위치가 어긋나지 않게
        text = text[: s.start] + _TOKENS[s.kind] + text[s.end :]
    return text


def scrub_value(value: Any) -> Any:
    """문자열, 숫자, 딕셔너리(키 포함), 목록 안쪽까지 재귀로 지운다.

    숫자는 문자로 바꿔 검사하고, 번호로 읽히면 토큰 문자열로 바꾼다. 저장할 수 없는 형식(집합·바이트 등)과
    지운 뒤 키가 겹치는 딕셔너리는 값이 조용히 사라지지 않게 ValueError 로 거부한다.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, int | float):
        cleaned = scrub_text(str(value))
        return cleaned if cleaned != str(value) else value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            clean_key = scrub_text(str(key))
            if clean_key in out:
                raise ValueError("개인정보를 지운 뒤 딕셔너리 키가 겹친다")
            out[clean_key] = scrub_value(item)
        return out
    if isinstance(value, list | tuple):
        return [scrub_value(v) for v in value]
    raise ValueError(f"저장할 수 없는 값 형식이다: {type(value).__name__}")
