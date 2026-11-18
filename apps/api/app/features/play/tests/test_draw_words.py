"""이게 뭐게 가비 추천: 공개 단어 목록과 일정·대화에서 단어 찾기. AI 는 부르지 않는다."""

import re

from app.features.play import draw_words

EXAMPLES = ["케이크", "딸기", "선물", "텐트", "꽃다발", "해바라기", "돈가스", "돼지", "바다"]


def test_word_list_is_clean():
    words = draw_words.load_words()
    assert len(words) >= 150
    for word, item in words.items():
        assert re.fullmatch(r"[가-힣]{1,5}", word), word  # 띄어쓰기·합성어 없는 한 단어
        assert item.word == word
        for alt in item.alts:
            assert re.fullmatch(r"[가-힣A-Za-z]{1,5}", alt), (word, alt)  # 정답 변형은 영문 약어(pc)도 허용
            assert alt != word
    for word in EXAMPLES:
        assert word in words, word


def test_word_list_has_no_duplicates_in_file():
    import json

    raw = json.loads(draw_words.WORDS_PATH.read_text(encoding="utf-8"))
    names = [row["word"] for row in raw]
    assert len(names) == len(set(names))


def test_find_words_examples():
    assert draw_words.find_words("딸기 케이크 사 갈게") == ["딸기", "케이크"]
    assert draw_words.find_words("흑돼지 먹었다") == ["돼지"]
    assert draw_words.find_words("협재 바다색") == ["바다"]
    assert draw_words.find_words("협재 해변") == []  # 고유 지명은 목록에 없다
    assert draw_words.find_words("해바라기 꽃다발 준비") == ["해바라기", "꽃다발"]


def test_find_words_has_no_duplicates_and_keeps_order():
    assert draw_words.find_words("텐트 치고 케이크 먹고 또 텐트") == ["텐트", "케이크"]
    assert draw_words.find_words("") == []


def test_single_char_words_need_noun_token():
    assert "집" in draw_words.load_words()
    assert draw_words.find_words("집에 갔다") == ["집"]
    assert draw_words.find_words("집중해서 봤다") == []
