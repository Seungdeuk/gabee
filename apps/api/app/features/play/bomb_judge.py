"""문장 폭탄 "끝났나" 판정. 형태소 분석기 Kiwi 로 마지막 형태소가 종결어미(EF)인지 본다.

판정 값: "Y" 문장을 끝냈다(게임에서 생명 -1), "N" 끝나지 않았다(통과), "H" 미정(통과로 다룬다).
규칙 전체는 bomb_rules.json (위키 sentence-end-engine, 원본 prj/model-eval_end/scripts/kiwi_eval.py 를 옮김).
- 조사 없이 체언(명사·대명사·수사)으로 끝나면 끝낸 것으로 본다(바다·하나). 조사가 붙거나 부사면 통과.
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
    last_word = pre.split()[-1] if pre.split() else ""
    if any(t in last_word for t in RULES["typo_patterns"]):
        return "Y"  # 심한 오타(목록): 마지막 어절만 본다. 앞에 나온 오타 때문에 뒤 사람이 탈락하면 안 된다
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
    if tag in RULES["bare_noun_tags"] and form not in RULES["bare_noun_exceptions"]:
        return "Y"  # 조사·어미 없이 명사·대명사·수사로 끝남(바다·김치찌개·하나). 조사가 붙으면(바다가) 통과, 부사(어제·너무)도 통과
    return "N"


def _syllables(final: int) -> str:
    """받침 번호가 final 인 한글 음절 전부(정규식 글자 모음에 쓴다)."""
    return "".join(chr(c) for c in range(0xAC00, 0xD7A4) if (c - 0xAC00) % 28 == final)


_RIEUL = "[" + _syllables(8) + "]"  # 받침 ㄹ (할·갈·먹을의 을 은 따로)
_SIOT = "[" + _syllables(19) + "]"  # 받침 ㅅ (햇·갓: 했·갔을 잘못 쓴 것)
_BIEUP = "[" + _syllables(17) + "]"  # 받침 ㅂ (갑·합·입)

# 끝말 사전: 마지막 말의 끝이 아래 모양이면 Kiwi 분석과 상관없이 정한다. 가장 길게 맞는 쪽이 이기고 같으면 허용이 이긴다.
# 문장부호를 뗀 문장 끝에서 찾는다. 두 가지로 읽히는 말(-다고·-다니·-나)은 넣지 않고 Kiwi 에 맡긴다.
TAIL_BLOCK = [  # 연결·관형형이라 문장을 끝내지 않는다(통과)
    "으?려다가?", "다가", "으?려고", "다면", "더니", "자마자", r"까\s*봐", "니까", "는데", "던", "다는", "[을ㄹ]?텐데",
    "(?<![았었했겠아])니",  # 비가 오니(= 비가 와서). 했니·아니는 종결로 둔다
]  # fmt: skip
TAIL_ALLOW = [  # 문장을 끝낸다(탈락)
    f"(?:{_RIEUL}|을)걸요?", f"(?:{_RIEUL}|을)게요?", "잖아요?", "더라(?:고)?", "던데요?", "거든요", "는데요",
    "다니까요?", "[았었했]나", "다[능규]", f"{_SIOT}어요?", "습니다", "습니까", f"{_BIEUP}니다", f"{_BIEUP}니까",
]  # fmt: skip


def tail_verdict(text: str) -> str | None:
    """끝말 사전 판정: 종결이면 "Y", 통과면 "N", 사전에 없으면 None."""
    best_len, best = 0, None
    for patterns, verdict in ((TAIL_BLOCK, "N"), (TAIL_ALLOW, "Y")):
        for pat in patterns:
            m = re.search(f"(?:{pat})$", text)
            if m and (len(m.group()) > best_len or (len(m.group()) == best_len and verdict == "Y")):
                best_len, best = len(m.group()), verdict
    return best


def _retry_typo_coda(text: str, tokens: list[tuple[str, str]]) -> bool:
    """마쳫다처럼 받침이 틀려 통째로 명사로 읽힌 말: 다 앞 음절 받침을 ㅆ 으로 바꿔 다시 읽어 종결이면 참."""
    last = text.split()[-1]
    if len(last) < 2 or not last.endswith("다") or not tokens or tokens[-1][1] == "EF":
        return False
    code = ord(last[-2]) - 0xAC00
    if not 0 <= code < 11172 or code % 28 == 0:
        return False  # 받침 없는 음절(바다·사다)은 건드리지 않는다
    fixed = text[:-2] + chr(0xAC00 + code - code % 28 + 20) + "다"
    again = _get_kiwi().tokenize(preprocess(fixed), normalize_coda=True)
    return judge_tokens([(t.form, t.tag) for t in again], fixed) == "Y"


def _eojeols(text: str) -> list[list[str]]:
    """교정한 문장을 어절마다 형태소 태그 목록으로 나눈다."""
    out: list[list[str]] = [[] for _ in text.split()]
    starts, pos = [], 0
    for chunk in text.split():
        pos = text.index(chunk, pos)
        starts.append(pos)
        pos += len(chunk)
    for t in _get_kiwi().tokenize(text):
        idx = max(i for i, st in enumerate(starts) if st <= t.start)
        out[idx].append(t.tag)
    return out


def is_multi_phrase(word: str) -> bool:
    """한 번에 여러 어절을 이어 썼으면 참(그것만으로 탈락). 띄어 썼는지가 아니라 교정 결과로 본다.

    띄어쓰기 교정 뒤 한 어절이면 한 구절이다(그 것도·김치 찌개·하려 다). 두 어절 이상이어도
    명사끼리 붙은 말에 조사가 붙은 것(우리 가족은·할머니 댁에·사과 주스)은 한 구절로 본다.
    여러 어절로 보는 때: 3어절 이상이거나, 마지막 어절에 동사·형용사가 있거나(밥 먹고·시장 가서·안 돼),
    마지막 앞 어절이 조사로 끝날 때(엄마가 학교에·비가 오니).
    """
    squeezed = "".join(word.split())
    if any("".join(e.split()) == squeezed for e in RULES["multi_phrase_exceptions"]):
        return False  # 띄어 쓰는 고정 표현(그리고 나서)은 한 구절로 본다
    stripped = " ".join(word.split())
    if any(re.fullmatch(p, stripped) for p in RULES["multi_phrase_exception_patterns"]):
        return False  # 그만두려고 하니·결혼했다고하니처럼 -고 하니 꼴은 한 구절로 본다(앞에 다른 말이 붙으면 해당 없음)
    fixed = _get_kiwi().space(word, reset_whitespace=True)
    words = _eojeols(fixed)
    if len(words) < 2:
        return False
    if len(words) >= 3:
        return True  # 3어절 이상은 무조건 여러 어절(엄마 아빠 그리고)
    last_text = fixed.split()[-1]
    verbal = any(t.startswith("V") or t in ("XSV", "XSA") for t in words[-1]) or (
        last_text in RULES["bare_noun_exceptions"]
    )  # 산(샀던의 줄임)은 명사로 읽혀도 서술어로 본다
    josa_before = any(w and w[-1].startswith("J") for w in words[:-1])
    return verbal or josa_before


def fix_spacing(word: str) -> str:
    """띄어쓰기 교정으로 한 어절이 되는 말(그 것도·아 니)은 합친 형태로 돌려준다. 그 밖에는 그대로."""
    if len(word.split()) < 2:
        return word
    fixed = _get_kiwi().space(word, reset_whitespace=True)
    return fixed if len(fixed.split()) == 1 else word


def judge_sentence(text: str) -> str:
    """지금까지 이어 말한 문장 전체를 판정한다. "Y" 면 마지막으로 말한 사람이 문장을 끝낸 것이다."""
    text = text.strip()
    if not text:
        return "N"
    asked = text.endswith("?")
    text = (
        re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅣ]+$", "", text) or text
    )  # 끝 문장부호는 뗀다(분석을 흔든다)
    last = text.split()[-1]
    if re.fullmatch(r"[ㄱ-ㅣ]+", _key(last)):
        return "Y"  # 마지막 말이 자음·모음만(ㅋㅋ·ㅠㅠ·ㅇㅇ·ㅏ·ㅇㅁㄹㅇㄻ)이면 길이와 상관없이 탈락
    if is_repeat_word(last):
        return "Y"  # 네네·응응처럼 대답을 되풀이한 말
    if _key(last) in RULES["one_word_answers"]:
        return "Y"  # 대답류(응·네·아니·그래…)는 문장 어디서든 마지막 말이 이것이면 탈락
    if asked and text.endswith("니"):
        return "Y"  # 비가 오니? 는 묻는 말이라 끝낸 것
    verdict = tail_verdict(text)
    if verdict is not None:
        return verdict
    tokens = [(t.form, t.tag) for t in _get_kiwi().tokenize(preprocess(text), normalize_coda=True)]
    result = judge_tokens(tokens, text)
    if result != "Y" and _retry_typo_coda(text, tokens):
        return "Y"
    return result


def is_ended(text: str) -> bool:
    """게임에서 문장을 끝낸 것으로 칠지. 미정(H)은 통과시킨다."""
    return judge_sentence(text) == "Y"
