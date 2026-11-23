"""E5 신규 사례 본문 파일의 로더·검증기(E5b 개발 36건, E5c 검증·테스트 36건이 쓴다).

검증 함수는 모두 순수 함수이고 위반은 `CaseFileError`(= `ScenarioError`)로 알린다. 메시지에 사례 id 를 넣는다.
도구 결과 비교(금지 문자열이 도구 결과에서 새는지)는 E5b 에서 `Observation` 확장 없이 러너가 도구 결과를 기록하는 방식으로
추가한다(운영 코드 변경 없음). 이번에는 구현하지 않는다.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from pydantic import ValidationError

from .scenarios import (
    LISTED_SPLITS,
    SCENARIO_CATEGORIES,
    SPLIT_TOTALS,
    TOPICS,
    WORLD_OF_SPLIT,
    ScenarioError,
    ScenarioItem,
    ScenarioList,
    normalize,
)
from .schema import Case, Split
from .seeds import data as seed_data
from .seeds import worlds
from .write_tools import WRITE_TOOLS

# 문자 3-gram 자카드 유사도 임계. 근거(2026-11-12, 확정 목록 72건+레거시 52건의 분할 사이 질문 쌍 실측): 실제 쌍의 최댓값이 0.39 이고
# 질문 한 단어만 바꾼 변형은 0.60~0.74 였다(예: 토요일→일요일 0.74, 이번 달→지난달 0.64, 치과→병원 0.60). 0.8 은 단어 교체 변형을
# 놓치므로 오탐 여유(0.39)와 변형 하한(0.60) 사이인 0.5 로 정했다.
TEMPLATE_SIMILARITY_LIMIT = 0.5
DEFAULT_ASKER = seed_data.FAMILY_USERS[0]  # as_user 가 없으면 질문자는 지민이다
SECURITY_SCENARIOS = frozenset({"cross_family", "injection"})


class CaseFileError(ScenarioError):
    """사례 파일 오류."""


# ---- 불러오기 -----------------------------------------------------------------------------------


def load_cases(path: Path, split: Split) -> list[Case]:
    """한 분할의 사례 파일(JSON 배열)을 읽는다. 모든 사례가 `Case` 형식이고 합성이며 분할이 같아야 한다."""
    if split == "legacy":
        raise CaseFileError("legacy 사례는 adapter.load_legacy_cases 로 읽는다")
    if not Path(path).exists():
        raise CaseFileError(f"{split} 분할 사례 파일이 없다: {path}")
    try:
        rows = json.loads(Path(path).read_text("utf-8"))
    except json.JSONDecodeError as e:
        raise CaseFileError(f"{path} 가 JSON 이 아니다: {e}") from e
    if not isinstance(rows, list):
        raise CaseFileError(f"{path} 는 사례 배열이어야 한다")
    if not rows:
        raise CaseFileError(f"{path} 가 비어 있다(사례가 하나도 없다)")
    cases = []
    for i, row in enumerate(rows):
        try:
            case = Case.model_validate(row)
        except ValidationError as e:
            name = row.get("id", f"#{i}") if isinstance(row, dict) else f"#{i}"
            raise CaseFileError(f"{name}: 사례 형식 오류: {e}") from e
        if case.split != split:
            raise CaseFileError(f"{case.id}: 분할이 {case.split} 인데 {split} 파일에 들어 있다")
        cases.append(case)
    return cases


# ---- a. id 유일 --------------------------------------------------------------------------------


def check_unique_ids(cases: Sequence[Case], legacy: Sequence[Case] = ()) -> None:
    ids = Counter(c.id for c in (*cases, *legacy))
    dup = sorted(i for i, n in ids.items() if n > 1)
    if dup:
        raise CaseFileError(f"사례 id 가 겹친다(레거시 포함): {dup}")


# ---- b. 같은 질문 조합 --------------------------------------------------------------------------


def _key(case: Case) -> tuple[str, str, str, str]:
    s = case.setup
    return (normalize(case.question), s.audience, s.room or "", s.as_user or "")


def check_no_overlap(cases: Sequence[Case], legacy: Sequence[Case] = ()) -> None:
    """(질문, audience, room, as_user) 조합이 정규화 후 같으면 분할 사이든 같은 분할 안이든 오류다."""
    seen: dict[tuple, Case] = {}
    for c in (*legacy, *cases):
        k = _key(c)
        if k in seen:
            o = seen[k]
            if o.split == "legacy" and c.split == "legacy":
                continue  # 기존 52건 안에는 같은 질문 조합이 이미 있다(b-poisoned·m-poisoned-data). 새 사례와의 겹침만 본다
            where = "같은 분할" if o.split == c.split else f"{o.split}·{c.split} 사이"
            raise CaseFileError(f"{c.id}: {o.id} 와 같은 질문 조합이다({where})")
        seen[k] = c


# ---- c. 템플릿 중복 -----------------------------------------------------------------------------


def _grams(text: str) -> set[str]:
    t = normalize(text)
    return {t[i : i + 3] for i in range(len(t) - 2)} or {t}


def similarity(a: str, b: str) -> float:
    """문자 3-gram 자카드 유사도."""
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb)


def find_similar_across_splits(
    items: Iterable[tuple[str, str, str]], limit: float = TEMPLATE_SIMILARITY_LIMIT
) -> Iterator[tuple[str, str, float]]:
    """(id, 분할, 질문) 중 서로 다른 분할 사이에서 유사도가 limit 이상인 쌍."""
    rows = list(items)
    for i, (ia, sa, qa) in enumerate(rows):
        for ib, sb, qb in rows[i + 1 :]:
            if sa != sb and (sim := similarity(qa, qb)) >= limit:
                yield ia, ib, sim


def check_templates(cases: Sequence[Case], legacy: Sequence[Case] = ()) -> None:
    rows = [(c.id, c.split, c.question) for c in (*legacy, *cases)]
    for a, b, sim in find_similar_across_splits(rows):
        raise CaseFileError(f"{b}: {a} 와 질문이 거의 같다(3-gram 유사도 {sim:.2f}, 같은 템플릿)")


# ---- d. 목록과 일치 -----------------------------------------------------------------------------


def check_matches_list(
    cases: Sequence[Case],
    lst: ScenarioList,
    *,
    require_complete: bool = False,
    splits: Iterable[str] | None = None,
) -> None:
    """사례가 확정 목록의 항목과 id·분할·범주·유형·경로·setup·질문이 같은지 본다.

    `require_complete=True` 면 `splits`(기본: 사례들이 속한 분할)의 모든 목록 항목에 사례가 있어야 한다.
    """
    by_id = {s.id: s for s in lst.scenarios}
    for c in cases:
        s = by_id.get(c.id)
        if s is None:
            raise CaseFileError(f"{c.id}: 확정 목록에 없는 사례다")
        got = {
            "split": c.split, "category": c.category, "scenario": c.scenario, "agent_path": c.agent_path,
            "audience": c.setup.audience, "room": c.setup.room, "as_user": c.setup.as_user,
            "question": c.question.strip(),
            "seed": c.setup.seed, "history": len(c.setup.history),
        }  # fmt: skip
        want = {
            "split": s.split, "category": s.category, "scenario": s.scenario, "agent_path": s.agent_path,
            "audience": s.setup_hint.audience, "room": s.setup_hint.room, "as_user": s.setup_hint.as_user,
            "question": s.question_signature.strip(),
            "seed": s.setup_hint.seed, "history": s.setup_hint.history_turns,
        }  # fmt: skip
        diff = [k for k in got if got[k] != want[k]]
        if diff:
            raise CaseFileError(f"{c.id}: 목록과 다르다({', '.join(diff)})")
    if require_complete:
        if not cases:
            raise CaseFileError("사례가 없다(require_complete 는 사례 0건을 통과시키지 않는다)")
        covered = {c.id for c in cases}
        wanted = set(splits) if splits is not None else {c.split for c in cases}
        missing = sorted(s.id for s in lst.scenarios if s.split in wanted and s.id not in covered)
        if missing:
            raise CaseFileError(f"목록의 사례가 빠졌다({len(missing)}건): {missing[:5]}")


# ---- e. 월드 격리 -------------------------------------------------------------------------------


def check_world(
    cases: Sequence[Case], lst: ScenarioList, *, require_runnable: bool = False
) -> None:
    by_id = {s.id: s for s in lst.scenarios}
    for c in cases:
        s = by_id.get(c.id)
        if s is None:
            raise CaseFileError(f"{c.id}: 확정 목록에 없는 사례다")
        if s.world_id != WORLD_OF_SPLIT.get(c.split):
            raise CaseFileError(
                f"{c.id}: {c.split} 분할 사례가 월드 {s.world_id} 에 있다(월드 격리 위반)"
            )
        if require_runnable and lst.worlds[s.world_id].status != "built":
            raise CaseFileError(f"{c.id}: 월드 {s.world_id} 가 아직 만들어지지 않아 실행할 수 없다")
        if require_runnable and s.needs:
            raise CaseFileError(f"{c.id}: 월드에 더해야 할 시드가 남아 있다: {s.needs}")


# ---- f. 보안 ------------------------------------------------------------------------------------


_ALL_WRITE_TOOLS = frozenset().union(*WRITE_TOOLS.values())


def _world_data(case: Case):
    """사례 분할의 월드 데이터 선언 모듈. 월드가 없는 분할(test, w3 는 아직 없다)은 기존처럼 w1 로 본다(test 사례는 이 단계에서 만들지 않는다)."""
    try:
        return worlds.data_of_split(case.split)
    except ValueError:
        return seed_data


def check_security(
    case: Case, risk: str | None = None, private_targets: Sequence[str] = ()
) -> None:
    """보안 사례 검사.

    - `cross_family`·`injection` 유형(위험을 모르면)이거나 위험이 `leak`·`injection` 이면 금지 문자열이 비어 있지 않아야 하고,
      모두 `seeds.data.forbidden_strings(as_user)` 에 들어 있어야 한다(비어 있지 않다는 것만으로는 통과하지 못한다).
      `private_targets`(목록이 정한 노리는 표식)는 모두 금지 문자열에 들어 있어야 한다: 엉뚱한 비공개 문자열 하나로 통과할 수 없다.
    - 금지 문자열이 질문이나 `setup.history` 의 어느 turn 에 (정규화 후) 들어 있으면 거부한다. 사용자가 준 문자열을 정상으로
      되풀이한 답을 누출로 오판하지 않게 한다.
    - 위험이 `write` 면 금지 문자열을 억지로 요구하지 않고, 쓰기 도구가 `forbidden_writes` 나 `forbidden_tools` 에 있어야 한다.
    `audience=room` 이어도 이 검사는 `as_user` 기준이다(방 구성원을 합친 기준은 러너가 답에 적용한다).
    """
    sec = case.expect.security
    if risk == "write":
        if not (set(sec.forbidden_writes) | set(sec.forbidden_tools)) & _ALL_WRITE_TOOLS:
            raise CaseFileError(
                f"{case.id}: 쓰기 위험 사례는 forbidden_writes 나 forbidden_tools 에 쓰기 도구가 있어야 한다"
            )
        return
    needs = (
        risk in {"leak", "injection"}
        or (risk is None and case.scenario in SECURITY_SCENARIOS)
        or bool(private_targets)
    )
    if not needs:
        return
    strings = sec.forbidden_strings
    if not strings:
        raise CaseFileError(f"{case.id}: 보안 사례는 forbidden_strings 가 비어 있으면 안 된다")
    seeds = _world_data(
        case
    )  # 사례의 월드(dev=w1, val=w2)의 값으로 본다: val 사례가 dev 월드의 값으로 검사되는 일이 없다
    user = case.setup.as_user or DEFAULT_ASKER
    if user not in seeds.ALL_USERS:
        raise CaseFileError(f"{case.id}: as_user {user} 가 합성 월드에 없다")
    private = set(seeds.forbidden_strings(user))
    visible = [m.text for m in (*seeds.MARKERS, *seeds.TOKENS) if user in m.visible_to]
    for s in strings:
        if s not in private:
            if any(s in v or v in s for v in visible):
                raise CaseFileError(
                    f"{case.id}: 금지 문자열 {s!r} 은 {user} 가 정당하게 보는 글에 들어 있다"
                )
            raise CaseFileError(
                f"{case.id}: 금지 문자열 {s!r} 이 {user} 에게 비공개인 합성 데이터(seeds.data)에서 온 것이 아니다"
            )
        n = normalize(s)
        if n in normalize(case.question):
            raise CaseFileError(f"{case.id}: 금지 문자열 {s!r} 이 질문에 들어 있다")
        for i, turn in enumerate(case.setup.history):
            if n in normalize(turn.text):
                raise CaseFileError(
                    f"{case.id}: 금지 문자열 {s!r} 이 setup.history[{i}] 에 들어 있다"
                )
    missing = [t for t in private_targets if t not in strings]
    if missing:
        raise CaseFileError(
            f"{case.id}: 목록의 private_targets {missing} 가 forbidden_strings 에 모두 들어 있어야 한다"
        )


# ---- g. 정규식 ----------------------------------------------------------------------------------


_GROUP_PREFIX = re.compile(r"\?(?:[:=!]|<[=!]|P<[^>]+>)")
_BRACE = re.compile(r"\{(\d*)(?:(,)(\d*))?\}")


def _repeats(p: str, i: int) -> bool:
    """p[i:] 가 상한 2 이상(또는 무제한)인 반복 수량자인가. `?`·`{0,1}`·`{1}` 은 아니다."""
    if i >= len(p):
        return False
    if p[i] in "+*":
        return True
    m = _BRACE.match(p, i)
    if not m or (not m.group(1) and not m.group(3)):
        return False
    if m.group(2):
        return not m.group(3) or int(m.group(3)) >= 2
    return int(m.group(1)) >= 2


def _skip_class(p: str, i: int) -> int:
    """`[` 위치 i 에서 문자 클래스 끝 다음 위치를 돌려준다."""
    i += 1
    if i < len(p) and p[i] == "^":
        i += 1
    if i < len(p) and p[i] == "]":
        i += 1
    while i < len(p) and p[i] != "]":
        i += 2 if p[i] == "\\" else 1
    return i + 1


def _risky_inside(body: str) -> bool:
    r"""반복되는 그룹 안에 선택(|)·내부 수량자·`.`·`\w`·`\d` 같은 넓은 낱말이 있으면 True."""
    m = _GROUP_PREFIX.match(body)
    i = m.end() if m else 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 < len(body) and body[i + 1] in "wdsWDS":
                return True
            i += 2
            continue
        if ch == "[":
            i = _skip_class(body, i)
            continue
        if ch in "|.+*?" or (ch == "{" and _BRACE.match(body, i)):
            return True
        i += 1
    return False


def nested_quantifier(pattern: str) -> bool:
    r"""반복(+, *, {n,m} 상한 2 이상·무제한)되는 그룹 안에 선택·내부 수량자·`.`·`\w`·`\d` 가 있으면 True.

    `(a+)+`·`(a*)*`·`(a|aa)+`·`(a|a)+`·`(.|a)+`·`(\w|\d)+`·`(a+){2,50}`·`(?:a|a?)+` 가 모두 걸린다(보수적인 휴리스틱:
    `(치과|병원)+` 같은 정상 패턴도 거부한다. 반복하지 않는 `(치과|병원)` 은 허용한다).
    """
    stack: list[int] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            i = _skip_class(pattern, i)
            continue
        if ch == "(":
            stack.append(i + 1)
        elif ch == ")" and stack:
            start = stack.pop()
            if _repeats(pattern, i + 1) and _risky_inside(pattern[start:i]):
                return True
        i += 1
    return False


def _regex_values(case: Case) -> Iterator[str]:
    for call in case.expect.calls:
        for m in call.args:
            if m.match == "regex" and isinstance(m.value, str):
                yield m.value


def check_regexes(case: Case) -> None:
    for pattern in _regex_values(case):
        if nested_quantifier(pattern):
            raise CaseFileError(f"{case.id}: 중첩 수량자 정규식은 쓸 수 없다: {pattern}")


# ---- h. 일정 쓰기 -------------------------------------------------------------------------------


def named_tools(case: Case) -> set[str]:
    """`runner.unsupported_reason` 이 보는 것과 같은 도구 이름 모음(기대·금지·calls)."""
    e = case.expect
    return {
        *e.tools.required,
        *e.tools.forbidden,
        *(c.tool for c in e.calls),
        *e.security.forbidden_tools,
        *e.security.forbidden_writes,
    }


def classify_support(case: Case) -> str:
    """`runner.unsupported_reason` 과 같은 기준: `setup.seed` 가 있거나 일정 쓰기 도구가 든 신규 사례는 "unsupported"."""
    if case.setup.seed is not None or named_tools(case) & WRITE_TOOLS["schedule"]:
        return "unsupported"
    return "supported"


# ---- i. 분포 ------------------------------------------------------------------------------------


def check_distribution(lst: ScenarioList) -> None:
    """주제별·분할별 개수와 유형↔범주 분포(요구사항 표의 '주로 나오는 범주')를 본다."""
    counts = Counter((s.topic, s.split) for s in lst.scenarios)
    for topic, t in TOPICS.items():
        for sp in LISTED_SPLITS:
            if counts[(topic, sp)] != t.per_split[sp]:
                raise CaseFileError(
                    f"주제 {topic} 의 {sp} 는 {t.per_split[sp]}건이어야 한다(현재 {counts[(topic, sp)]})"
                )
        total = sum(counts[(topic, sp)] for sp in LISTED_SPLITS)
        if total < 6:
            raise CaseFileError(f"주제 {topic} 는 최소 6건이어야 한다(현재 {total})")
    per_split = Counter(s.split for s in lst.scenarios)
    for sp, n in SPLIT_TOTALS.items():
        if per_split[sp] != n:
            raise CaseFileError(f"{sp} 분할은 {n}건이어야 한다(현재 {per_split[sp]})")
    for s in lst.scenarios:
        if s.category not in SCENARIO_CATEGORIES[s.scenario]:
            raise CaseFileError(f"{s.id}: {s.scenario} 유형은 범주 {s.category} 에 나오지 않는다")


def check_scenarios_overlap(lst: ScenarioList) -> None:
    """목록 단계의 중복: 질문이 분할 사이에서 같은 템플릿이면 오류(레거시 질문은 사례 단계에서 본다)."""
    for a, b, sim in find_similar_across_splits(
        (s.id, s.split, s.question_signature) for s in lst.scenarios
    ):
        raise CaseFileError(f"{b}: {a} 와 질문이 거의 같다(3-gram 유사도 {sim:.2f})")


def check_case_security_fields(case: Case, item: ScenarioItem) -> None:
    """목록의 risk·private_targets 까지 반영한 보안 검사."""
    check_security(case, item.risk, item.private_targets)


def validate_cases(
    cases: Sequence[Case],
    lst: ScenarioList,
    legacy: Sequence[Case] = (),
    *,
    require_complete: bool = False,
    require_runnable: bool = False,
    splits: Iterable[str] | None = None,
) -> None:
    """E5b·E5c 가 사례 파일을 저장하기 전에 부르는 전체 검사."""
    check_unique_ids(cases, legacy)
    check_no_overlap(cases, legacy)
    check_templates(cases, legacy)
    check_matches_list(cases, lst, require_complete=require_complete, splits=splits)
    check_world(cases, lst, require_runnable=require_runnable)
    by_id = {s.id: s for s in lst.scenarios}
    for c in cases:
        check_case_security_fields(c, by_id[c.id])
        check_regexes(c)
        if classify_support(c) == "unsupported":
            raise CaseFileError(
                f"{c.id}: 일정 쓰기 도구가 든 사례는 정상 사례가 아니라 unsupported 목록에 둔다"
            )


def legacy_cases() -> list[Case]:
    """레거시 52건의 사례(중복 검사용). 어댑터를 늦게 불러 L0 시험이 무거운 import 를 피한다."""
    from .adapter import load_legacy_cases

    return [lc.case for lc in load_legacy_cases()]


__all__ = [
    "CaseFileError",
    "check_distribution",
    "check_matches_list",
    "check_no_overlap",
    "check_regexes",
    "check_scenarios_overlap",
    "check_security",
    "check_templates",
    "check_unique_ids",
    "check_world",
    "classify_support",
    "legacy_cases",
    "load_cases",
    "nested_quantifier",
    "similarity",
    "validate_cases",
]
