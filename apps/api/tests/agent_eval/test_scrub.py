"""스크러버 시험(L0). 기존 개인정보 탐지기(detect)를 재사용하는지 본다."""

import pytest

from evals.agent_eval.scrub import scrub_text, scrub_value


@pytest.mark.parametrize(
    "text, token",
    [
        ("연락처 010-1234-5678 로", "[전화번호]"),
        ("01012345678", "[전화번호]"),
        ("02-123-4567", "[전화번호]"),
        ("a.b@example.com 으로 보내", "[이메일]"),
        ("주민번호 900101-1234567", "[주민번호]"),
        ("카드 4111 1111 1111 1111", "[카드번호]"),
        ("카드 4111-1111-1111-1111", "[카드번호]"),
        ("０１０-１２３４-５６７８", "[전화번호]"),  # 전각 숫자
        ("010​1234​5678", "[전화번호]"),  # 폭 없는 문자
        ("010–1234–5678", "[전화번호]"),  # en dash
    ],
)
def test_personal_looking_strings_are_replaced_even_in_disguised_forms(text, token):
    out = scrub_text(text)
    assert token in out
    assert "1234" not in out and "example.com" not in out and "4111" not in out


@pytest.mark.parametrize(
    "text", ["회비 2010원 참석 1234명", "2026-10-05 일정", "총 1,234,567원", "치과 3시", ""]
)
def test_ordinary_text_is_left_alone(text):
    assert scrub_text(text) == text


def test_synthetic_names_are_evaluation_content_and_are_kept():
    assert scrub_text("김철수와 박영희 일정") == "김철수와 박영희 일정"


def test_scrubbing_is_idempotent():
    once = scrub_text("010-1234-5678 / a@b.com / 900101-1234567")
    assert scrub_text(once) == once


def test_nested_values_and_dict_keys_are_scrubbed_and_ordinary_values_are_kept():
    value = {
        "title": "010-1234-5678",
        "010-9999-0000": ["a@b.com", {"n": 3, "ok": True, "none": None, "x": 1.5}],
        "tuple": ("900101-1234567", 7),
    }
    out = scrub_value(value)
    assert out["title"] == "[전화번호]"
    assert "[전화번호]" in out and "010-9999-0000" not in out
    assert out["[전화번호]"] == ["[이메일]", {"n": 3, "ok": True, "none": None, "x": 1.5}]
    assert out["tuple"] == ["[주민번호]", 7]


def test_numbers_that_read_as_identifiers_are_replaced():
    assert scrub_value({"n": 9001011234567, "small": 1000}) == {"n": "[주민번호]", "small": 1000}


def test_unsupported_types_and_colliding_keys_are_rejected_instead_of_dropped():
    for bad in ({1, 2}, b"bytes", object()):
        with pytest.raises(ValueError):
            scrub_value({"x": bad})
    with pytest.raises(ValueError):
        scrub_value({"010-1111-2222": 1, "010-3333-4444": 2})  # 지운 뒤 키가 같아진다
