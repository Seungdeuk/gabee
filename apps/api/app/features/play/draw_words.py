"""이게 뭐게 가비 추천의 "공개 단어 목록"과, 일정·대화 글자에서 그 목록의 단어를 찾는 함수.

- 목록(`draw_words.json`)은 선 그림으로 알아볼 수 있는 흔한 사물 한 단어(띄어쓰기·합성어 없음)만 둔다. 고유명사·이름·장소·행동은 없다.
  그래서 일정·대화에서 목록에 있는 단어만 뽑으면 개인정보가 섞이지 않는다(AI 에는 이 단어만 보낸다).
- 두 글자 이상은 공백을 뺀 글자에서 부분 문자열로 찾는다(예: "흑돼지"에서 "돼지", "딸기 케이크"에서 "딸기"·"케이크").
- 한 글자 단어("집", "새")는 "집중"·"새로" 같은 말에 걸리지 않도록 Kiwi 형태소 분석으로 명사 토큰이 정확히 그 글자일 때만 인정한다.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .bomb_judge import _get_kiwi

WORDS_PATH = Path(__file__).with_name("draw_words.json")
_NOUN_TAGS = ("NNG", "NNP")


@dataclass(frozen=True)
class DrawWord:
    word: str
    alts: tuple[str, ...]  # 이것도 정답(예: 케이크 → 케익)


@cache
def load_words() -> dict[str, DrawWord]:
    rows = json.loads(WORDS_PATH.read_text(encoding="utf-8"))
    return {row["word"]: DrawWord(row["word"], tuple(row.get("alts", []))) for row in rows}


def find_words(text: str) -> list[str]:
    """text 에서 목록 단어를 글자에 나온 순서대로, 중복 없이 돌려준다."""
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return []
    words = load_words()
    found: dict[str, int] = {}
    singles: set[str] = set()
    for word in words:
        if len(word) >= 2:
            at = compact.find(word)
            if at >= 0:
                found[word] = at
        elif word in compact:
            singles.add(word)
    if singles:
        for token in _get_kiwi().tokenize(text):
            if token.tag in _NOUN_TAGS and token.form in singles and token.form not in found:
                found[token.form] = compact.find(token.form)
    return sorted(found, key=found.__getitem__)
