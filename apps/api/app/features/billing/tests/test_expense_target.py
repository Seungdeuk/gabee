"""삭제 대상 특정 검사(`billing/target.py`)의 순수 함수 시험. DB·모델 호출 없음."""

from dataclasses import dataclass

import pytest

from app.features.billing import target


@dataclass(frozen=True)
class E:
    id: str
    title: str
    amount: int
    date: str


A = E("a", "수진이 학원비", 80000, "2026-11-05")
B = E("b", "학원비", 120000, "2026-11-20")
C = E("c", "문구류", 6000, "2026-11-07")
D = E("d", "장보기", 30000, "2026-11-08")
D2 = E("d2", "장보기", 45000, "2026-11-12")
POOL = [A, B, C, D, D2]


def _ok(question, expense, pool=POOL):
    target.ensure_identified(question, expense, pool)


def _refused(question, expense, pool=POOL):
    with pytest.raises(ValueError) as e:
        target.ensure_identified(question, expense, pool)
    return str(e.value)


@pytest.mark.parametrize(
    "question",
    ["지난번에 낸 지출 지워 줘", "그거 지워 줘", "내 지출 하나 지워 줘", "", "지출 지워 줘"],
)
def test_a_request_without_title_amount_or_date_is_refused_for_any_expense(question):
    for expense in POOL:
        assert "어느 지출" in _refused(question, expense)


def test_the_refusal_lists_candidates_so_the_assistant_can_ask():
    message = _refused("지난번에 낸 지출 지워 줘", A)
    assert (
        "수진이 학원비 80,000원(2026-11-05)" in message
        and "삭제 확인 카드를 만들지 말고" in message
    )


@pytest.mark.parametrize(
    ("question", "expense"),
    [
        ("수진이 학원비 지워 줘", A),  # 제목 전체
        ("문구류 지워 줘", C),  # 제목 한 단어
        ("6,000원 지출 지워 줘", C),  # 금액(쉼표)
        ("6000원짜리 지워 줘", C),  # 금액(쉼표 없음)
        ("12만원 쓴 학원비 지워 줘", B),  # 금액(만원)
        ("11월 7일 지출 지워 줘", C),  # 날짜(월·일)
        ("2026-11-07 지출 지워 줘", C),  # 날짜(ISO)
        ("11/7 지출 지워 줘", C),  # 날짜(슬래시)
        ("7일에 쓴 거 지워 줘", C),  # 날짜(일만, 같은 일이 하나뿐)
    ],
)
def test_a_clear_request_passes(question, expense):
    _ok(question, expense)


def test_the_best_match_wins_when_more_than_one_kind_is_mentioned():
    _ok("11월 5일 수진이 학원비 지워 줘", A)  # 제목+날짜가 맞는 A 가 제목만 맞는 B 보다 낫다
    _ok("학원비 120,000원 지워 줘", B)  # 제목+금액


def test_a_more_specific_mention_does_not_let_the_model_pick_the_looser_match():
    assert "어느 지출" in _refused("수진이 학원비 지워 줘", B)  # 문장은 더 구체적인 A 를 가리킨다
    assert "어느 지출" in _refused("학원비 120,000원 지워 줘", A)  # 금액까지 맞는 B 가 있다
    assert "여러 건" in _refused("학원비 지워 줘", A)  # '학원비' 만 말하면 둘 다 후보다


def test_a_title_shared_by_several_expenses_is_ambiguous():
    message = _refused("장보기 지워 줘", D)
    assert "여러 건" in message and "장보기 30,000원" in message and "장보기 45,000원" in message
    _ok("장보기 45,000원 지워 줘", D2)  # 금액을 더하면 하나로 정해진다
    _ok("11월 8일 장보기 지워 줘", D)  # 날짜를 더해도 정해진다


def test_naming_another_expense_does_not_identify_the_chosen_one():
    # 문장은 문구류를 가리키는데 모델이 장보기를 골랐다
    assert "어느 지출" in _refused("문구류 지워 줘", D)
    assert "어느 지출" in _refused("6,000원 지출 지워 줘", A)


def test_generic_words_do_not_identify_anything():
    for word in ("지출", "비용", "결제", "내역", "정산"):
        assert "어느 지출" in _refused(
            f"{word} 지워 줘", E("x", f"{word} 정리", 1000, "2026-11-01")
        )


def test_small_numbers_are_dates_not_amounts():
    assert target.mentioned_amounts("5일에 3번 쓴 거") == set()
    assert target.mentioned_amounts("5천원") == {5000}
    assert target.mentioned_amounts("3만5천원") == {35000}
    assert target.mentioned_amounts("8만원") == {80000}
    assert target.mentioned_amounts("80,000원") == {80000}
    assert target.mentioned_dates("11월 5일과 2026-10-01") == [(2026, 10, 1), (None, 11, 5)]
