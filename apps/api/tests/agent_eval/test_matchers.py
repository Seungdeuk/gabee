"""인자 매처 시험(L0)."""

import pytest

from evals.agent_eval.matchers import matches, text_contains

OCT = {"from": "2026-10-01", "to": "2026-10-31"}
NAN = float("nan")


@pytest.mark.parametrize(
    "kind, expected, actual, ok",
    [
        ("eq", "2026-10", "2026-10", True),
        ("eq", 60000, "60000", True),
        ("eq", 60000, "60000.0", True),
        ("eq", 60000.0, 60000, True),
        ("eq", 60000, " 60000 ", True),
        ("eq", "a ", "a", True),
        (
            "eq",
            "60000",
            "60000.0",
            False,
        ),  # 둘 다 문자열이면 숫자로 보지 않는다(아이디·우편번호 보호)
        ("eq", "a", "b", False),
        ("eq", 5, "５", False),  # 전각 숫자는 숫자로 보지 않는다
        ("eq", True, "True", True),
        ("eq", True, "true", True),
        ("eq", True, " TRUE ", True),
        ("eq", False, "true", False),
        ("eq", 1, True, False),
        ("eq", "None", None, False),
        ("eq", "x", ["x"], False),
        ("eq", "x", {"x": 1}, False),
        ("eq", NAN, "nan", False),
        ("eq", "nan", NAN, False),
        ("contains", "병원", "엄마랑 병원 가기", True),
        ("contains", "60,000", "60000원", True),
        ("contains", "60000", 60000.0, True),
        ("contains", "inf", float("inf"), True),  # 무한대는 숫자로 정규화하지 않고 문자열로 본다
        ("contains", "치과", ["병원", "치과"], True),
        ("contains", "치과", ("병원", "치과"), True),
        ("contains", "치과", {"병원", "치과"}, True),
        ("contains", "치과", ["병원"], False),
        ("contains", "치과", [None, "치과"], True),
        ("contains", "치과", [None], False),
        ("contains", "치과", [{"x": "치과"}], False),
        ("contains", "치과", [["치과"]], False),
        ("contains", "a", {"a": 1}, False),
        ("contains", "None", None, False),
        ("contains", ",", "abc", False),
        ("regex", r"^\d{2}:\d{2}$", "09:30", True),
        ("regex", r"^\d{2}:\d{2}$", "9:30", False),
        ("regex", r"^\d+$", 60000.0, True),
        ("regex", "a", "xay", True),  # 앞뒤가 붙어 있어도 search 로 찾는다
        ("regex", "a", ["a"], False),
        ("regex", "a", {"a": 1}, False),
        ("date_range", OCT, "2026-10-15", True),
        ("date_range", OCT, "2026-10-01", True),
        ("date_range", OCT, "2026-10-31", True),
        ("date_range", OCT, "2026-09-30", False),
        ("date_range", OCT, "2026-11-01", False),
        ("date_range", OCT, "2026-10-15 09:30", True),
        ("date_range", OCT, "2026-10-15T09:30:00+09:00", True),
        ("date_range", OCT, "내일", False),
        ("date_range", OCT, "20261015", False),
        ("date_range", OCT, 20261015, False),
        ("date_range", OCT, "2026-W42-1", False),
        ("date_range", OCT, "2026-10-15XYZ", False),
        ("date_range", OCT, "2026-10-15 garbage", False),
        ("date_range", OCT, "2026-10-15Tgarbage", False),
        ("date_range", OCT, "2026-10-15T25:99", False),
        ("date_range", OCT, "2026-10-15T", False),
        ("date_range", OCT, "2026-10-15 ~ 2026-11-20", False),
        ("date_range", OCT, "2026-10-15 또는 2026-12-25", False),
        ("date_range", OCT, "2026-02-30", False),
        ("date_range", OCT, ["2026-10-15"], False),
        ("any_of", ["me", "room"], "room", True),
        ("any_of", [1, 2], "3", False),
        ("any_of", [1, 2], "2", True),
        ("any_of", ["a"], ["a"], False),
    ],
)
def test_matches(kind, expected, actual, ok):
    assert matches(kind, expected, actual) is ok


def test_unknown_matcher_kind_raises_even_for_missing_values():
    with pytest.raises(ValueError):
        matches("fuzzy", "a", "a")
    with pytest.raises(ValueError):
        matches("fuzzy", "a", None)


def test_text_contains_ignores_thousands_commas_on_both_sides():
    assert text_contains("총 60,000원이에요", "60000")
    assert text_contains("총 60000원이에요", "60,000")
    assert not text_contains("총 50,000원이에요", "60,000")


def test_text_contains_never_matches_a_blank_needle():
    assert not text_contains("abc", ",")
    assert not text_contains("abc", ",,")
    assert not text_contains("abc", "  ")
    assert not text_contains("", ",")
