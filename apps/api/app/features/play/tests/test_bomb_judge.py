"""문장 폭탄 끝남 판정(Kiwi): 사용자가 정한 규칙표와 처음 보는 문장 55개 표본."""

import csv
from pathlib import Path

import pytest

from app.features.play.bomb_judge import (
    fix_spacing,
    is_ended,
    is_multi_phrase,
    is_repeat,
    is_repeat_word,
    judge_sentence,
    preprocess,
)

CASES = [
    # (문장, 끝났나) — 위키 sentence-end-engine 의 규칙표
    ("밥 먹었어요", True),  # 일반 종결어미
    ("알겠어요", True),
    ("어디 가니?", True),  # 의문형
    ("정말 예쁘구나", True),  # 감탄형
    ("오늘 배고픔", True),  # -음/-함
    ("숙제함", True),
    ("사과요", True),  # 명사+요
    ("저요", True),
    ("다다다", True),  # 꼼수: 같은 글자 반복
    ("가나다라", True),  # 꼼수: 나열
    ("ㅋㅋㅋ", True),  # 꼼수: ㅋㅋ
    ("응", True),  # 한 단어 대답
    ("네.", True),
    ("그래서 어떻게 됐는데", False),  # -는데 는 통과
    ("밥 먹고", False),  # 연결
    ("나는 학교에", False),
    ("바다", True),  # 조사 없이 명사로 끝나면 탈락(11/10 규칙)
    ("엄마가 어", True),
    ("나는 음", True),
    ("엄마가 글쎄", True),
    ("엄마가 맞아", True),
    ("나는 좋아", True),
    ("엄마가 응", True),  # 대답류는 문장 중간에서도 마지막 말이면 탈락
    ("나는 네", True),
    ("엄마가 그래", True),
    ("오늘 응 응", True),
    ("나 아니", True),
    ("응 그래서", False),  # 그래서·아니면은 다른 말이라 통과
    ("그게 아니면", False),
    ("산", False),  # 샀던의 줄임이라 통과
    ("바다가", False),  # 조사가 붙으면 통과
    ("오늘 저녁 메뉴는 김치찌개", True),
    ("우리", True),
    ("우리는", False),
    ("하나", True),
    ("하나도", False),
    ("엄마가 어제", False),  # 부사(어제·오늘·너무·그리고)는 통과
    ("엄마가 오늘", False),
    ("너무", False),
    ("엄마 아빠 그리고", False),
    ("누가 어제 학교에서", False),
]


@pytest.mark.parametrize(("text", "ended"), CASES)
def test_rule_table(text, ended):
    assert is_ended(text) is ended, (text, judge_sentence(text))


@pytest.mark.parametrize(
    "text",
    [
        "ㅋㅋ", "ㅋㅋㅋ", "ㅋㅋㅋㅋ", "ㅠㅠ", "ㅎㅎ", "ㅇㅇ", "ㄴㄴ", "ㅈㅈ",
        "ㅏ", "ㅓ", "ㅗ", "ㅛ", "ㅇㅁㄹㅇㄻ", "ㅋㅋ!",
        "나는 ㅋㅋㅋ", "엄마가 ㅠㅠ", "오늘 학교에서 ㅇㅇ", "나는 ㅏ",
    ],
)  # fmt: skip
def test_jamo_only_last_word_is_ended(text):
    assert is_ended(text) is True, (text, judge_sentence(text))


def test_jamo_attached_to_a_word_follows_normal_rules():
    assert is_ended("나는 학교에ㅋㅋ") is False


def test_empty_is_not_ended():
    assert judge_sentence("") == "N"
    assert judge_sentence("   ") == "N"


def test_preprocess_cleans_noise():
    assert preprocess("먹었어ㅋㅋㅋ") == "먹었어"
    assert preprocess("좋아아아아") == "좋아"
    assert preprocess("했어욬") == "했어요"


def test_sentence_context_matters():
    # 한 단어씩 이어 말해도 문장 전체로 본다: 마지막 말이 문장을 끝내는 순간 걸린다
    words = ["엄마가", "어제", "시장에서", "사과를", "샀다"]
    for i in range(1, len(words)):
        assert not is_ended(" ".join(words[:i]))
    assert is_ended(" ".join(words))


LONG_OPEN = "엄마가 밥을 맛있게 지었는데 고라니가 와서 귀엽게 훔쳐가려다"


def test_long_chained_sentence_only_the_last_morpheme_counts():
    """연결어미(-는데, -서, -려다)가 여러 번 나와도 맨 끝만 본다. 끝이 연결어미면 통과, 다/EF 로 끝내면 탈락."""
    assert not is_ended(LONG_OPEN)
    assert is_ended(LONG_OPEN + " 생쥐가 토끼랑 같이 먹었다")
    words = (LONG_OPEN + " 생쥐가 토끼랑 같이 먹고 아주 오래 즐겁게 놀다가 잠이 들었는데").split()
    assert len(words) >= 15 and not is_ended(" ".join(words))  # 15단어가 넘는 긴 문장도 읽힌다


def _rows(name):
    path = Path(__file__).with_name(f"bomb_sentences_{name}.tsv")
    return [
        r
        for r in csv.DictReader(path.open(encoding="utf-8"), delimiter="	")
        if r["expect_end"] in ("Y", "N")
    ]


def _wrong(name):
    return [
        (r["text"], r["expect_end"], judge_sentence(r["text"]))
        for r in _rows(name)
        if (judge_sentence(r["text"]) == "Y") != (r["expect_end"] == "Y")
    ]


# v4(가족 테스트에서 틀린 말): 지금은 모두 맞는다. 못 고치는 말이 생기면 여기에 적는다.
V4_KNOWN_MISSES: set[str] = set()
# 산(샀던)을 명사 산(山)으로 읽어서 틀린다. 조사 없는 명사 규칙(11/10) 뒤에 생긴 오판.
V1_KNOWN_MISSES: set[str] = set()


@pytest.mark.parametrize(
    ("name", "known_misses"),
    [("v1", V1_KNOWN_MISSES), ("v2", set()), ("v3", set()), ("v4", V4_KNOWN_MISSES)],
)
def test_sentence_sets(name, known_misses):
    """model-eval_end 에서 쓴 문장 3세트(약 165개). v3 는 규칙을 만든 뒤 처음 본 문장이다(네네 같은 대답 반복을 막는 규칙을 넣어 0개)."""
    assert len(_rows(name)) >= 50
    assert {text for text, *_ in _wrong(name)} <= known_misses, _wrong(name)


def test_repeating_an_answer_inside_one_word():
    for w in ("네네", "응응", "네네네", "아니아니", "그래그래", "넵넵"):
        assert is_repeat_word(w), w
        assert is_ended(w), w  # 문장 판정에서도 탈락
    # 자연스러운 흉내말·평범한 말은 대답이 아니라서 막지 않는다
    for w in ("깡충깡충", "펄펄", "두근두근", "네모", "아니면", "그래서"):
        assert not is_repeat_word(w), w


def test_repeating_a_word_already_said_in_this_sentence():
    # 바로 앞 말이든 더 앞의 말이든 이번 문장에서 이미 나온 말이면 반복이다
    assert is_repeat("밥을", ["밥을"])
    assert is_repeat("나는", ["나는", "어제"])
    assert is_repeat("나는", ["어제", "학교에서", "나는"])
    assert is_repeat("그리고!", ["어제", "그리고"])  # 문장부호·공백은 무시
    assert is_repeat("Apple", ["apple"])
    # 비슷하지만 다른 말은 반복이 아니다
    assert not is_repeat("밥이", ["밥을"])
    assert not is_repeat("먹었다", ["밥을"])
    assert not is_repeat("누가", [])
    assert not is_repeat("...", ["!!!"])  # 비교할 글자가 없으면 반복으로 보지 않는다


@pytest.mark.parametrize(
    ("word", "multi"),
    [
        ("그 것도", False),  # 띄어쓰기 실수는 한 구절
        ("김치 찌개", False),
        ("하려 다", False),
        ("강아지 가", False),
        ("바다", False),  # 처음부터 한 어절
        ("어제 산", True),  # 산(샀던의 줄임)이 붙은 두 어절
        ("그만두려하니", False),  # -고 하니 꼴은 한 구절
        ("결혼했다하니", False),
        ("그만두려고하니", False),
        ("결혼했다고하니", False),
        ("결혼했다고 하니", False),
        ("엄마가 그만두려고하니", True),  # 앞에 다른 말이 붙으면 여러 어절
        ("우리 가족은", False),  # 명사끼리 + 조사는 한 구절
        ("할머니댁에", False),
        ("사과주스", False),
        ("밥먹고", True),  # 붙여 써도 문법상 두 어절
        ("시장가서", True),
        ("엄마가학교에", True),
        ("안돼", True),
        ("그리고나서", False),  # 예외 목록
        ("그리고 나서", False),  # 예외 목록의 고정 표현
        ("시장 가서", True),  # 여러 어절을 이어 쓰면 탈락
        ("밥 먹고", True),
        ("엄마가 학교에", True),
        ("할 수 있어", True),
        ("엄마 아빠 그리고", True),
    ],
)
def test_multi_phrase_input(word, multi):
    assert is_multi_phrase(word) is multi


def test_fix_spacing_merges_only_single_phrases():
    assert fix_spacing("아 니") == "아니"  # 합치면 대답류라 탈락해야 한다
    assert is_ended(fix_spacing("아 니")) is True
    assert fix_spacing("그 것도") == "그것도"
    assert fix_spacing("시장 가서") == "시장 가서"  # 진짜 두 어절은 그대로
    assert fix_spacing("바다") == "바다"
