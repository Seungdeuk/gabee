"""문장 폭탄 "끝났나" 판정. 형태소 분석기 Kiwi 로 마지막 형태소가 종결어미(EF)인지 본다.

판정 값: "Y" 문장을 끝냈다(게임에서 생명 -1), "N" 끝나지 않았다(통과), "H" 미정(통과로 다룬다).
규칙 전체는 bomb_rules.json (위키 sentence-end-engine, 원본 prj/model-eval_end/scripts/kiwi_eval.py 를 옮김).
- 꼼수(가나다·같은 글자 반복·자음모음 나열·ㅋㅋ)·변형 말투(했당·그랬삼)·한 단어 대답(응·네)·심한 오타(목록)는 끝낸 것으로 본다.
- -는데/-거든은 통과, 명사+요·-음/-함은 인정하는 규칙은 사용자가 정했다.
LLM 은 쓰지 않는다. Kiwi 는 처음 쓸 때 한 번 불러와 재사용한다(불러오기 약 1초, 판정은 문장당 약 0.1ms).
"""

import json
import re
import threading
from pathlib import Path

RULES = json.loads((Path(__file__).with_name("bomb_rules.json")).read_text(encoding="utf-8"))

# Kiwi 는 받침을 조합형 자모(ᆸ, ᆫ …)로 돌려준다. 규칙 비교를 위해 호환 자모(ㅂ, ㄴ …)로 바꾼다.
_JONG = dict(zip("ᆨᆩᆪᆫᆬᆭᆮᆯᆰᆱᆲᆳᆴᆵᆶᆷᆸᆹᆺᆻᆼᆽᆾᆿᇀᇁᇂ", "ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ", strict=True))

_kiwi = None
_lock = threading.Lock()


def _get_kiwi():
    global _kiwi
    if _kiwi is None:
        with _lock:
            if _kiwi is None:
                from kiwipiepy import Kiwi  # 무거운 모듈이라 처음 쓸 때 불러온다

                _kiwi = Kiwi()
    return _kiwi


def _norm_form(s: str) -> str:
    return "".join(_JONG.get(c, c) for c in s)


def preprocess(text: str) -> str:
    """잡음 전처리: 홀로 쓴 ㅋㅎㅠㅜ 삭제, 끝 글자 받침 ㅋ/ㅎ 제거, 같은 글자 3번 이상은 1번으로. 문장부호는 둔다."""
    t = re.sub(r"[ㅋㅎㅠㅜ]+", "", text)
    m = re.search(r"([가-힣])([^가-힣]*)$", t)
    if m:
        code = ord(m.group(1)) - 0xAC00
        if code % 28 in (24, 27):  # 받침 ㅋ, ㅎ
            t = t[: m.start(1)] + chr(0xAC00 + code - code % 28) + t[m.end(1) :]
    return re.sub(r"([가-힣])\1{2,}", r"\1", t)


_KEY_DROP = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅣ]")


def _key(word: str) -> str:
    """같은 말인지 비교하려고 공백·문장부호를 없애고 소문자로 맞춘다."""
    return _KEY_DROP.sub("", word).casefold()


def is_repeat_word(word: str) -> bool:
    """한 말 안에서 대답을 되풀이했는지(네네·응응·아니아니). 깡충깡충·펄펄 같은 흉내말은 자연스러운 말이라 대답 목록의 말만 본다."""
    key = _key(word)
    for unit in RULES["one_word_answers"]:
        n = len(unit)
        if len(key) >= 2 * n and len(key) % n == 0 and key == unit * (len(key) // n):
            return True
    return False


def is_repeat(word: str, before: list[str]) -> bool:
    """방금 한 말이 이번 문장에서 이미 나온 말(바로 앞 말이든 더 앞의 말이든)이거나 대답을 되풀이한 것이면 참이다."""
    key = _key(word)
    return is_repeat_word(word) or (bool(key) and key in {_key(w) for w in before})


def judge_tokens(tokens: list[tuple[str, str]], text: str) -> str:
    """(형태, 품사) 목록과 원문으로 Y/N/H 를 정한다."""
    real = [
        (f, t) for f, t in tokens if not any(t.startswith(p) for p in RULES["skip_tag_prefixes"])
    ]
    pre = preprocess(text)
    if re.fullmatch(r"([가-힣])\1{2,}[^가-힣]*", text.strip()):
        return "Y"  # 같은 글자만 반복(다다다)
    if re.fullmatch(r"이?요[^가-힣]*", pre.strip()):
        return "Y"  # 요만 남음
    if not real:
        return "Y"  # 내용 없음(ㅋㅋㅋ·이모지만)
    if re.match(RULES["nonsense_noun_pattern"], "".join(f for f, _ in real)):
        return "Y"  # 의미 없는 나열(가나다…)
    if re.search(r"[ㄱ-ㅣ]이?요[^가-힣]*$", pre):
        return "Y"  # 자음·모음만 나열 + 요
    if any(t in pre for t in RULES["typo_patterns"]):
        return "Y"  # 심한 오타(목록)
    form, tag = real[-1]
    form = _norm_form(form)
    if tag == "Z_CODA":
        return "Y"  # 받침을 덧붙인 변형 말투(했당)
    if form in RULES["variant_end_forms"] and len(real) > 1 and real[-2][1] == "EP":
        return "Y"  # 변형 말투(그랬삼)
    if len(real) == 1 and tag == "IC":
        return "Y"  # 한 단어 대답(응·네)
    has_pred = any(t in RULES["predicate_tags"] for _, t in real[:-1])
    yo = RULES["polite_yo"]
    if len(real) == 1 and form in RULES["one_word_answers"]:
        return "Y"
    if tag == "EC" and form in RULES["final_ec_forms"] and has_pred:
        return "Y"  # 문장 끝의 다·니 등이 연결어미로 읽힌 종결
    if tag in RULES["end_tags"] or (tag == yo["tag"] and form.endswith(yo["suffix"])):
        if not has_pred and tag != yo["tag"]:
            return "Y"  # 어미 앞에 동사·형용사 없음(꼼수)
        if form in RULES["reject_end_forms"]:
            return "N"  # -는데/-거든은 종결로 보지 않는다
        if tag == yo["tag"]:
            before = real[:-1]
            if before and before[-1][1].startswith("J"):
                before = before[:-1]
            noun = before[-1] if before else None
            if noun is None or not (
                noun[1] in RULES["yo_noun_tags"] or noun[0] in RULES["yo_extra_nouns"]
            ):
                return "Y"  # 요 앞이 명사가 아님(꼼수)
            return "Y"  # 명사+요
        return "Y"  # 종결어미
    if tag in RULES["house_tags"]:
        return "H"  # 명사형 어미 -음/-함(집 규칙)
    return "N"


def judge_sentence(text: str) -> str:
    """지금까지 이어 말한 문장 전체를 판정한다. "Y" 면 마지막으로 말한 사람이 문장을 끝낸 것이다."""
    text = text.strip()
    if not text:
        return "N"
    if is_repeat_word(text.split()[-1]):
        return "Y"  # 네네·응응처럼 대답을 되풀이한 말
    tokens = _get_kiwi().tokenize(
        preprocess(text), normalize_coda=True, typos="basic_with_continual_and_lengthening"
    )
    return judge_tokens([(t.form, t.tag) for t in tokens], text)


def is_ended(text: str) -> bool:
    """게임에서 문장을 끝낸 것으로 칠지. 미정(H)은 통과시킨다."""
    return judge_sentence(text) == "Y"
