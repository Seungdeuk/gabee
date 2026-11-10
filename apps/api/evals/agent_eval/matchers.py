"""인자 매처. 사례의 기대값과 실제 인자를 비교한다."""

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
_DATE_PREFIX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_KINDS = ("eq", "contains", "regex", "date_range", "any_of")


def _num(value: Any) -> Decimal | None:
    """숫자로 읽히면 Decimal, 아니면 None(NaN·무한대 포함)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) or (
        isinstance(value, str) and _NUMBER.fullmatch(value.strip())
    ):
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    return None


def _norm(value: Any) -> str:
    """비교용 문자열. 숫자는 60000.0 과 60000 이 같게 만든다."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float) and (number := _num(value)) is not None:
        return format(number.normalize(), "f")
    return str(value).strip()


def text_contains(text: str, needle: str) -> bool:
    """부분 문자열 비교. 금액 쉼표는 있어도 없어도 같게 본다(기존 tab_agents 와 같은 규칙).

    금액처럼 정확해야 하는 값은 `eq` 로 비교한다(쉼표를 무시해서 `1,000` 이 `21000` 에도 들어간다).
    쉼표·공백뿐인 needle 은 항상 일치해 버리므로 False 로 둔다(사례를 불러올 때도 거부한다).
    """
    core = needle.replace(",", "")
    if not core.strip():
        return False
    return needle in text or core in text.replace(",", "")


def _eq(expected: Any, actual: Any) -> bool:
    if any(isinstance(v, float) and not math.isfinite(v) for v in (expected, actual)):
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return str(expected).strip().lower() == str(actual).strip().lower()
    if isinstance(expected, int | float) or isinstance(actual, int | float):
        a, b = _num(expected), _num(actual)
        if a is not None and b is not None:  # 한쪽이 숫자일 때만 숫자 문자열도 숫자로 본다
            return a == b
    return _norm(actual) == _norm(expected)


def _in_range(rng: dict[str, str], actual: Any) -> bool:
    """문자열만 받는다. 날짜(YYYY-MM-DD) 또는 그 뒤에 시간이 붙은 ISO 형식 전체가 유효해야 한다.

    시간대는 변환하지 않고 적힌 날짜를 쓴다. 'YYYYMMDD'·주차 표기·숫자·범위 표기는 날짜로 보지 않는다.
    """
    if not isinstance(actual, str):
        return False
    text = actual.strip()
    if not _DATE_PREFIX.match(text):
        return False
    try:
        day = date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text).date()
    except ValueError:
        return False
    return date.fromisoformat(rng["from"]) <= day <= date.fromisoformat(rng["to"])


def matches(kind: str, expected: Any, actual: Any) -> bool:
    """kind 는 eq | contains | regex | date_range | any_of. 값 형태는 사례를 불러올 때 이미 검증된다.

    실제 값이 None 이거나 dict 이면 항상 False. eq·any_of·regex 는 목록 값이면 False 이고,
    contains 는 목록의 문자열·숫자 원소마다 본다. regex 는 정규화한 문자열에서 search 한다.
    """
    if kind not in _KINDS:
        raise ValueError(f"알 수 없는 매처: {kind}")
    if actual is None or isinstance(actual, dict):
        return False
    if kind == "contains":
        items = actual if isinstance(actual, list | tuple | set) else [actual]
        needle = _norm(expected)
        return any(
            text_contains(_norm(item), needle)
            for item in items
            if item is not None and not isinstance(item, dict | list | tuple | set)
        )
    if isinstance(actual, list | tuple | set):
        return False
    if kind == "eq":
        return _eq(expected, actual)
    if kind == "regex":
        return re.search(str(expected), _norm(actual)) is not None
    if kind == "date_range":
        return _in_range(expected, actual)
    return any(_eq(v, actual) for v in expected)  # any_of
