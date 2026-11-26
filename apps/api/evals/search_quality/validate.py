"""사례·월드 정합 검사. 어긋나면 `DatasetInvalid` 로 평가를 중단한다(점수를 내지 않는다).

검사하는 것
1. 키: gold·acceptable·forbidden 이 모두 선언된 메시지이고 서로 겹치지 않는다.
2. 범위: gold 는 요청자 가족 전체방의 지워지지 않은 글이어야 한다(에이전트가 볼 수 있는 글). forbidden 은 그 범위 밖이어야 한다(다른 가족·1:1·삭제글).
3. 핵심 사실: 사례의 key_facts 가 gold 글(카드는 카드 주석)에 모두 들어 있다. gold 가 없는 사례는 key_facts 도 없다.
4. 결과 없음의 진짜 없음: gold 가 없는 사례의 검색어가 범위 안 어떤 글에도 모두 들어 있지 않다(빈 결과가 정말 정답이다).
5. 미끼: forbidden 글은 이상적인 검색어의 낱말을 모두 포함한다(범위 위반이 생기면 검색에 걸려 눈에 띄게 한다).
6. 동의어·카드 표시의 일관성: lexical_gap 사례는 gold 글이 이상적 검색어의 낱말을 모두 갖지 않는다. card 사례는 gold 가 카드 글이다.
7. 검색어 묶음과 expected_cause 의 키가 같다(agent 슬롯은 비어 있어도 된다). 원인 값은 허용 목록 안에 있다.
"""

from . import data
from .attribution import CAUSES


class DatasetInvalid(RuntimeError):
    """평가셋 정의가 어긋나 점수를 낼 수 없다."""


def _has_all(text: str, words: list[str]) -> bool:
    low = text.lower()  # 운영 검색은 대소문자를 구분하지 않는 부분 문자열 일치(ILIKE)
    return all(w.lower() in low for w in words)


def check(cases: list[dict]) -> list[str]:
    """어긋난 항목의 설명 목록(비어 있으면 정합)."""
    msgs = data.by_key()
    scope = data.family_scope_keys()
    problems: list[str] = []
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        problems.append("사례 id 가 겹친다")
    for c in cases:
        cid = c["id"]
        gold, acc, forb = c["gold"], c["acceptable"], c["forbidden"]
        for key in (*gold, *acc, *forb):
            if key not in msgs:
                problems.append(f"{cid}: 선언되지 않은 메시지 키 {key}")
        if set(gold) & set(forb) or set(gold) & set(acc) or set(acc) & set(forb):
            problems.append(f"{cid}: gold·acceptable·forbidden 이 겹친다")
        if any(k not in msgs for k in (*gold, *acc, *forb)):
            continue
        for key in gold:
            if key not in scope:
                problems.append(
                    f"{cid}: gold {key} 가 에이전트 검색 범위(가족 전체방·미삭제) 밖이다"
                )
        for key in forb:
            if key in scope:
                problems.append(f"{cid}: forbidden {key} 가 검색 범위 안이다")
        pool = " ".join(msgs[k].text + " " + msgs[k].card for k in gold)
        for fact in c["key_facts"]:
            if fact not in pool:
                problems.append(f"{cid}: 핵심 사실 '{fact}' 이 gold 글에 없다")
        if not gold and c["key_facts"]:
            problems.append(f"{cid}: gold 가 없는데 key_facts 가 있다")
        if gold and not c["key_facts"]:
            problems.append(f"{cid}: gold 가 있는데 key_facts 가 비어 있다")
        ideal = c["queries"]["ideal"]
        if not gold:
            for name, words in c["queries"].items():
                if words and any(_has_all(msgs[k].text, words) for k in scope):
                    problems.append(
                        f"{cid}: 결과 없음 사례인데 {name} 검색어가 범위 안 글에 걸린다"
                    )
        for key in forb:
            if not _has_all(msgs[key].text, ideal):
                problems.append(f"{cid}: 미끼 {key} 가 이상적 검색어를 담지 않아 누출을 못 잡는다")
        if c["lexical_gap"] and any(_has_all(msgs[k].text, ideal) for k in gold):
            problems.append(f"{cid}: lexical_gap 인데 gold 글에 이상적 검색어가 들어 있다")
        if c["card"] and any(not msgs[k].card for k in gold):
            problems.append(f"{cid}: card 사례의 gold 가 카드 글이 아니다")
        if c["card"] and any(_has_all(msgs[k].text, ideal) for k in gold):
            problems.append(f"{cid}: 카드 글의 text 에 이상적 검색어가 들어 있다")
        if set(c["queries"]) != set(c["expected_cause"]):
            problems.append(f"{cid}: queries 와 expected_cause 의 묶음이 다르다")
        for name, cause in c["expected_cause"].items():
            if cause and cause not in CAUSES:
                problems.append(f"{cid}: 알 수 없는 원인 {cause} ({name})")
        if c["queries"]["ideal"] == []:
            problems.append(f"{cid}: ideal 검색어가 없다")
    return problems


def require(cases: list[dict]) -> None:
    problems = check(cases)
    if problems:
        raise DatasetInvalid("평가셋 정합 검사 실패: " + "; ".join(problems))
