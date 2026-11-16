"""L2 실행기 시험이 함께 쓰는 도우미(가짜 모델·합성 DB 만 쓴다, 실제 호출 없음)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals.agent_eval import adapter, fake_model
from evals.agent_eval.cost import Ledger
from evals.agent_eval.fake_model import call, say
from evals.agent_eval.runner import RunOptions, RunReport, run_cases
from evals.agent_eval.schema import Case


def legacy(*ids: str) -> list[adapter.LegacyCase]:
    """기존 사례 중 id 가 맞는 것을 사례 파일의 순서대로."""
    cases = adapter.load_legacy_cases()
    found = [c for c in cases if c.case.id in ids]
    assert {c.case.id for c in found} == set(ids), "없는 사례 id"
    return found


def run(
    items: list[Any],
    tmp_path: Path | None = None,
    *,
    run_id: str = "t",
    repeats: int = 1,
    scripts: Mapping[str, fake_model.Script] | None = None,
    ledger: Ledger | None = None,
    **option_fields: Any,
) -> RunReport:
    options = RunOptions(run_id=run_id, repeats=repeats, results_root=tmp_path, **option_fields)
    return run_cases(items, options, scripts=scripts, ledger=ledger)


def new_case(
    case_id: str = "n-1",
    *,
    split: str = "dev",
    agent_path: str = "billing",
    question: str = "2026년 10월 지출 합계 알려줘",
    setup: dict | None = None,
    expect: dict | None = None,
) -> Case:
    """신규 사례(합성) 하나."""
    return Case.model_validate(
        {
            "id": case_id,
            "split": split,
            "category": "D",
            "scenario": "single_tool",
            "agent_path": agent_path,
            "setup": setup or {},
            "question": question,
            "expect": expect or {},
            "meta": {"synthetic": True, "note": "시험용"},
        }
    )


def ask_billing_script(
    tool: str = "get_month_summary", args: dict | None = None, answer: str = "합계는 60,000원이에요"
) -> fake_model.Script:
    """메인이 ask_billing 을 부르고, 정산 Agent 가 `tool` 을 부른 뒤 답하는 대본."""
    return {
        "main": [call("ask_billing", {"question": "지출 알려줘"}), say(answer)],
        "billing": [call(tool, args if args is not None else {"month": "2026-10"}), say(answer)],
    }


def allow_synthetic(monkeypatch, items: list[Any]) -> None:
    """시험 전용: 합성 사례(`new_case`)를 '커밋된 사례'로 인정한다(실호출 경로의 커밋 대조 `runner.committed_rows` 를 바꾼다)."""
    from evals.agent_eval import runner

    real = runner.committed_rows
    extra = {runner._case_of(i).id: runner.case_row(i) for i in items}
    monkeypatch.setattr(runner, "committed_rows", lambda split: {**real(split), **extra})


def real_grant_for(
    items: list[Any],
    *,
    run_id: str = "r",
    approve: str = "1",
    results_root: Path | None = None,
    repeat: int = 1,
):
    """시험 전용: 사전 점검 기록을 만들고(`real_gate._mint_preflight`) 그 실행의 허가를 발급한다(활성은 아니다)."""
    from decimal import Decimal

    from evals.agent_eval import real_gate, runner

    split = runner._case_of(items[0]).split
    ids = [runner._case_of(i).id for i in items]
    digest = runner.case_fingerprint(items)
    record = real_gate._mint_preflight(
        run_id, Decimal(approve), split, frozenset(ids), Decimal("0.01"), digest, repeat
    )
    return real_gate.issue_grant(
        approve_usd=approve,
        split=split,
        case_ids=ids,
        known_ids=ids,
        run_id=run_id,
        preflight=record,
        content_hash=digest,
        repeat=repeat,
        results_root=results_root,
        environ={real_gate.ENV_NAME: "1"},
    )
