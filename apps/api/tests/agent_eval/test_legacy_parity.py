"""기존 52건 Golden Parity 시험(L0, LLM·DB 없음).

`tab_agents/run.py` 의 판정 부분을 그대로 옮긴 기준(`oracle`)과 새 어댑터(`adapter.judge`)가 같은 입력·관찰 결과에서
같은 판정(최종·네 부분)을 내는지 사례 id 별로 본다. 사례마다 모든 조건을 만족하는 관찰 하나와, 조건 하나씩만 깨뜨린 관찰들을
만들어 비교한다. 기존 실행기에는 실패 원인 분류가 없어 어느 부분이 틀렸는지(네 부분)로 비교한다.
기존 실행 결과(실제 LLM 답)는 파일로 남아 있지 않아서 관찰 결과는 사례 기대값에서 만든다.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass

import pytest

from evals.agent_eval.adapter import (
    LEGACY_CASES_PATH,
    LegacyCase,
    judge,
    load_legacy_cases,
)
from evals.agent_eval.schema import Observation, ToolCall

RAW = {r["id"]: r for r in json.loads(LEGACY_CASES_PATH.read_text("utf-8"))}
CASES = load_legacy_cases()
REGEX_SAMPLE = "수진이 낸 돈은 80,000원이에요"


def _contains(answer: str, text: str) -> bool:  # run.py 의 _contains
    return text in answer or text.replace(",", "") in answer.replace(",", "")


@dataclass(frozen=True)
class Seen:
    """기존 실행기가 판정에 쓰는 값."""

    answer: str
    can_answer: bool
    used: tuple[str, ...]  # 정산은 모든 도구 호출, 메인은 ask_ 호출만
    summaries: tuple[str, ...]


def oracle(case: dict, seen: Seen) -> dict[str, bool]:
    """`tab_agents/run.py` 의 판정을 그대로 옮긴 것(사례 파일의 키 이름 그대로)."""
    answer, used = seen.answer, list(seen.used)
    if case["agent"] == "main":
        want = case.get("main_tools")
        tool_ok = want is None or set(used) == set(want)
    elif case.get("tool_optional"):
        tool_ok = True
    elif case.get("tool_any"):
        tool_ok = any(t in used for t in case["tool_any"])
    else:
        tool_ok = (case["tool"] in used) if case["tool"] else not used
    text_ok = (
        all(_contains(answer, t) for t in case["expect_contains"])
        and (not case.get("expect_any") or any(_contains(answer, t) for t in case["expect_any"]))
        and not any(_contains(answer, t) for t in case.get("expect_not_contains", []))
        and not any(answer.strip().endswith(t) for t in case.get("expect_not_endswith", []))
        and not any(re.search(r, answer) for r in case.get("expect_not_regex", []))
    )
    proposals_ok = len(seen.summaries) == case.get("expect_proposals", 0)
    proposals_ok = proposals_ok and all(
        t in " ".join(seen.summaries) for t in case.get("expect_in_proposal", [])
    )
    return {
        "can_answer": seen.can_answer,
        "tool": tool_ok,
        "text": text_ok,
        "proposals": proposals_ok,
    }


def to_observation(legacy: LegacyCase, seen: Seen, nested=False) -> Observation:
    """기존 판정 입력을 새 관찰 결과로 바꾼다. nested 면 메인 관찰에 안쪽 Agent 호출을 함께 담는다."""
    stage = legacy.case.agent_path
    calls = [ToolCall(stage=stage, name=n) for n in seen.used]
    if nested and stage == "main":
        calls += [
            ToolCall(stage="billing", name="get_month_summary"),
            ToolCall(stage="main", name="plain_tool"),
        ]
    return Observation(
        calls=calls,
        answer=seen.answer,
        can_answer=seen.can_answer,
        proposals=list(seen.summaries),
    )


def perfect(raw: dict) -> Seen:
    """모든 조건을 만족하는 입력."""
    if raw["agent"] == "main":
        used = tuple(raw.get("main_tools") or ())
    elif raw.get("tool_optional"):
        used = ()
    elif raw.get("tool_any"):
        used = (raw["tool_any"][0],)
    else:
        used = (raw["tool"],) if raw["tool"] else ()
    parts = [*raw["expect_contains"], *raw.get("expect_any", [])[:1]]
    return Seen(
        answer=" ".join(parts) or "알겠어요",
        can_answer=True,
        used=used,
        summaries=tuple(raw.get("expect_in_proposal", []))
        + ("제안",)
        * max(0, raw.get("expect_proposals", 0) - len(raw.get("expect_in_proposal", []))),
    )


def mutations(raw: dict) -> list[tuple[str, Seen]]:
    """조건 하나씩만 깨뜨린 입력들."""
    base = perfect(raw)
    out: list[tuple[str, Seen]] = [("perfect", base)]

    def add(name: str, **changes) -> None:
        out.append((name, Seen(**{**base.__dict__, **changes})))

    add("no_tools", used=())
    add(
        "extra_tool",
        used=(*base.used, "ask_family_chat" if raw["agent"] == "main" else "zzz_extra"),
    )
    add("only_extra_tool", used=("ask_family_chat" if raw["agent"] == "main" else "zzz_extra",))
    add("cannot_answer", can_answer=False)
    add("empty_answer", answer="")
    add("one_proposal_more", summaries=(*base.summaries, "또 하나"))
    add("one_proposal_less", summaries=base.summaries[:-1] if base.summaries else ())
    add("no_proposals", summaries=())
    for tool in {*(raw.get("tool_any") or []), *(raw.get("main_tools") or []), raw.get("tool")} - {
        None
    }:
        add(f"missing_{tool}", used=tuple(u for u in base.used if u != tool))
    for needle in raw["expect_contains"]:
        add(f"drop_{needle}", answer=base.answer.replace(needle, ""))
    for needle in raw.get("expect_any", []):
        add(f"any_only_{needle}", answer=" ".join([*raw["expect_contains"], needle]))
    if raw.get("expect_any"):
        add("any_none", answer=" ".join(raw["expect_contains"]) or "알겠어요")
    for needle in raw.get("expect_not_contains", []):
        add(f"has_{needle}", answer=f"{base.answer} {needle}")
    for tail in raw.get("expect_not_endswith", []):
        add(f"ends_{tail}", answer=f"{base.answer} {tail}  ")
        add(f"mid_{tail}", answer=f"{tail} {base.answer}")
    for pattern in raw.get("expect_not_regex", []):
        assert re.search(pattern, REGEX_SAMPLE), "정규식 변이용 문장이 맞지 않는다"
        add("regex_hit", answer=f"{base.answer} {REGEX_SAMPLE}")
    for needle in raw.get("expect_in_proposal", []):
        add(
            f"proposal_lacks_{needle}",
            summaries=tuple(s.replace(needle, "") for s in base.summaries),
        )
    if raw.get("expect_in_proposal"):  # 제안마다 따로 있어도 이어 붙인 글에 있으면 통과(기존 방식)
        pieces = tuple(raw["expect_in_proposal"])
        add(
            "proposal_split_across",
            summaries=pieces + ("제안",) * max(0, raw.get("expect_proposals", 0) - len(pieces)),
        )
    return out


def _matrix():
    for legacy in CASES:
        raw = RAW[legacy.case.id]
        for name, seen in mutations(raw):
            for nested in (False, True) if legacy.case.agent_path == "main" else (False,):
                yield pytest.param(
                    legacy,
                    raw,
                    name,
                    seen,
                    nested,
                    id=f"{legacy.case.id}:{name}:{'n' if nested else 'p'}",
                )


@pytest.mark.parametrize(("legacy", "raw", "name", "seen", "nested"), list(_matrix()))
def test_every_legacy_case_is_judged_like_the_old_runner(legacy, raw, name, seen, nested):
    expected = oracle(raw, seen)
    got = judge(legacy, to_observation(legacy, seen, nested))
    assert dict(got.components) == expected, (legacy.case.id, name)
    assert got.legacy_passed == all(expected.values())
    assert got.passed == all(expected.values())  # 공통 보안 조건을 넘기지 않으면 기존 판정과 같다
    assert got.result.passed == all(expected.values()), (
        "일반 채점과 추가 검사를 합친 결과가 기존 판정과 다르다"
    )


def test_the_matrix_exercises_every_condition_kind_and_both_verdicts():
    seen_kinds = Counter()
    verdicts = Counter()
    for legacy in CASES:
        raw = RAW[legacy.case.id]
        for name, seen in mutations(raw):
            seen_kinds[
                name.split("_")[0]
                if name.startswith(("missing", "drop", "has", "ends", "mid", "any"))
                else name
            ] += 1
            verdicts[all(oracle(raw, seen).values())] += 1
    for kind in (
        "perfect",
        "no_tools",
        "extra_tool",
        "cannot_answer",
        "missing",
        "drop",
        "any",
        "ends",
        "mid",
        "regex_hit",
    ):
        assert seen_kinds[kind], kind
    assert verdicts[True] >= 52 and verdicts[False] > 52  # 통과·실패 판정이 모두 충분히 있다
    # 각 레거시 조건이 있는 사례마다 그 조건을 깨뜨려 실패하게 만든 입력이 있다
    for key, kind in (
        ("expect_any", "any_none"),
        ("expect_not_endswith", "ends"),
        ("expect_not_regex", "regex_hit"),
        ("expect_in_proposal", "proposal_lacks"),
    ):
        for raw in RAW.values():
            if raw.get(key):
                names = [
                    n
                    for n, s in mutations(raw)
                    if n.startswith(kind) and not all(oracle(raw, s).values())
                ]
                assert names, (raw["id"], key)


def test_failure_causes_are_only_tool_kinds_and_follow_the_tool_judgement():
    """기존 실행기에는 실패 원인 분류가 없다. 새 결과의 원인은 도구 판정과 같이 움직이는 도구 종류뿐이다."""
    for legacy in CASES:
        raw = RAW[legacy.case.id]
        for _, seen in mutations(raw):
            got = judge(legacy, to_observation(legacy, seen))
            assert set(got.result.failure_types) <= {"missing_tool", "wrong_tool"}
            if got.components["tool"]:
                assert not got.result.failure_types
            elif legacy.checks.tool_mode in ("exact", "any_of", "main_set", "none"):
                assert got.result.failure_types  # 도구 판정이 틀렸으면 원인이 적힌다
