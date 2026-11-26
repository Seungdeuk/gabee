"""실제 호출 전 사전 점검(L0, 실제 호출 0회): 항목마다 통과와 실패, 실패하면 `--real` 이 시작되지 않는다(전송 함수 호출 0), 키 값이 어디에도 안 나온다.

앱이 모델에게 보내려던 요청은 가짜 전송 함수로 가로챈다. 실제 전송 함수(`transport.post_messages` 원본)·httpx 가 불리면 시험이 즉시 실패한다.
"""

import logging
import os
from contextlib import contextmanager
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.features.ai_assistant.knowledge.verify import VERIFY_SYSTEM
from app.shared.config import settings
from app.shared.llm import transport
from evals.agent_eval import adapter, cli, env, fake_model, preflight, real_gate, runner, usage
from evals.agent_eval.cost import PRICES, Ledger, Scope, call_cost
from evals.agent_eval.preflight import FAIL, PASS, WARN, Check, PreflightInput, run_preflight
from tests.agent_eval.runner_support import legacy

CANARY = "sk-ant-canary-key-value-0003"
ORIGINAL_NER_PROBE = preflight.ner_probe
DEV_FILE = Path(runner.__file__).parent / "data" / "cases_dev.json"
PILOT_ONE = ("s-dev-01-routing-01",)
PILOT_NINE = (
    "s-dev-01-routing-01",
    "s-dev-01-routing-03",
    "s-dev-02-schedq-01",
    "s-dev-03-billing-01",
    "s-dev-03-billing-03",
    "s-dev-05-chat-01",
    "s-dev-06-docs-01",
    "s-dev-07-compound-01",
    "s-dev-10-isolation-01",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """카나리 키·환경변수·시험용 결과 폴더를 두고, 실제 전송·httpx 가 불리면 실패하게 한다. NER 점검은 별도 시험이 담당하므로 통과로 둔다."""
    monkeypatch.setattr(settings, "anthropic_api_key", CANARY)
    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(cli, "DEFAULT_RESULTS", tmp_path / "results")
    monkeypatch.setattr(cli, "DEFAULT_FAKE_RESULTS", tmp_path / "results" / "_fake")
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용 통과"))
    sent: list[int] = []

    def boom(*a, **k):
        sent.append(1)
        raise AssertionError("실제 호출을 시도했다")

    for target, name in (
        (httpx, "post"),
        (httpx, "request"),
        (httpx.Client, "send"),
        (httpx.AsyncClient, "send"),
        (transport, "post_messages"),
    ):
        monkeypatch.setattr(target, name, boom)
    return sent


@pytest.fixture
def quick_body(monkeypatch):
    """본문 점검(가짜 실행)을 건너뛰어 다른 항목 시험을 빠르게 한다(항목 4 는 아래에서 따로 시험한다)."""
    monkeypatch.setattr(
        preflight, "_fake_pass", lambda inp: (Check(4, "본문", PASS, "시험용 통과"), [], 0)
    )


def make_input(tmp_path, **kw):
    results = tmp_path / "results"
    base = dict(
        split="legacy",
        run_id="pf-1",
        approve=D("1"),
        model=settings.llm_model,
        repeat=1,
        requested_ids=("b-total",),
        items=legacy("b-total"),
        missing_ids=(),
        calls_per_case=4,
        tokens_in=8000,
        tokens_out=500,
        results_root=results,
        default_results=results,
        ledger=Ledger((Scope.RUN, Scope.PROJECT), opening={Scope.PROJECT: D(0)}),
        scripts={},
    )
    base.update(kw)
    return PreflightInput(**base)


def failed_numbers(report):
    return sorted(c.no for c in report.failed())


# ---------- 통과 ----------
def test_a_clean_run_passes_every_check_and_makes_a_record_without_any_real_call(
    tmp_path, isolated
):
    report = run_preflight(make_input(tmp_path))
    assert report.ok and [c.no for c in report.checks] == list(range(1, 10))
    assert {c.status for c in report.checks} <= {PASS, WARN}
    assert report.record is not None and report.record.case_ids == frozenset({"b-total"})
    assert report.record.run_id == "pf-1" and report.record.approve_usd == D("1")
    text = "\n".join(report.lines())
    assert "[통과]" in text and "모두 통과" in text and CANARY not in text
    assert isolated == []  # 실제 전송 함수·httpx 는 한 번도 불리지 않았다
    assert transport.post_messages is not None and real_gate.real_grant() is None


# ---------- 1·2: 키·모델·설정 ----------
def test_check_1_fails_without_a_key_and_never_prints_the_value(tmp_path, monkeypatch, quick_body):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    report = run_preflight(make_input(tmp_path))
    assert failed_numbers(report) == [1] and report.record is None
    assert "ANTHROPIC_API_KEY 가 없어" in "\n".join(report.lines())
    monkeypatch.setattr(
        settings, "anthropic_api_key", CANARY
    )  # 키가 있으면 값 없이 '있음' 만 적는다(길이도 적지 않는다)
    shown = "\n".join(run_preflight(make_input(tmp_path)).lines())
    assert "있음" in shown and CANARY not in shown and f"{len(CANARY)}자" not in shown


def test_check_2_fails_on_a_model_that_differs_from_the_settings(tmp_path, quick_body):
    report = run_preflight(make_input(tmp_path, model="claude-sonnet-5-5"))
    assert failed_numbers(report) == [2] and report.record is None
    assert "ANTHROPIC_MODEL" in report.checks[1].detail and CANARY not in report.checks[1].detail


def test_check_2_says_exactly_that_the_model_is_missing_from_the_price_table(
    tmp_path, monkeypatch, quick_body
):
    monkeypatch.setattr(settings, "llm_model", "claude-unknown-9")
    report = run_preflight(make_input(tmp_path, model="claude-unknown-9"))
    assert 2 in failed_numbers(report)
    assert "단가표에 없는 모델" in report.checks[1].detail
    assert "읽을 수 없다" not in "\n".join(report.lines())


def test_check_2_prints_the_token_and_step_settings(tmp_path, quick_body):
    detail = run_preflight(make_input(tmp_path)).checks[1].detail
    assert f"anthropic_max_tokens={settings.anthropic_max_tokens}" in detail
    assert f"MAX_STEPS={preflight._max_steps()}" in detail


def test_the_cli_reports_an_unknown_model_as_a_price_table_problem_not_a_case_read_error(tmp_path):
    for flag in ("--dry-run", "--real"):
        lines: list[str] = []
        argv = [flag, "--model", "claude-unknown-9", "--case", "b-total"]
        if flag == "--real":
            argv += ["--approve-usd", "1"]
        code = cli.main([*argv, "--results-dir", str(tmp_path / "results")], out=lines.append)
        text = "\n".join(lines)
        assert code == cli.REFUSED and "단가표에 없는 모델" in text and "읽을 수 없다" not in text


# ---------- 3: NER ----------
def test_check_3_wraps_the_probe_result(tmp_path, monkeypatch, quick_body):
    monkeypatch.setattr(preflight, "ner_probe", lambda: (False, "NER 로드·추론 실패(X)"))
    report = run_preflight(make_input(tmp_path))
    assert failed_numbers(report) == [3] and report.record is None


@pytest.fixture
def fresh_ner():
    from app.shared.privacy import ner

    ner.reset()
    yield ner
    ner.reset()


def test_the_probe_fails_when_the_mode_is_not_required(monkeypatch, fresh_ner):
    monkeypatch.setattr(settings, "privacy_ner_mode", "off")
    ok, detail = ORIGINAL_NER_PROBE()
    assert not ok and "required" in detail


def test_the_probe_fails_in_required_mode_when_the_model_folder_is_missing(
    tmp_path, monkeypatch, fresh_ner
):
    """필수 모드이므로 모델 파일이 없으면 실패하고 호출하지 않는다. 경로는 메시지에 적지 않는다."""
    missing = tmp_path / "no-such-ner-folder"
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(missing))
    ok, detail = ORIGINAL_NER_PROBE()
    assert not ok and "로드·추론 실패" in detail and str(missing) not in detail


def test_the_probe_passes_only_when_ner_really_finds_a_person_and_a_phone(monkeypatch, fresh_ner):
    from app.shared.privacy import ner
    from app.shared.privacy.types import Kind, Span

    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(ner, "reset", lambda: None)
    monkeypatch.setattr(ner, "ensure_ready", lambda: None)
    spans = [ner.NerSpan("PER", 0, 2, 0.9)]
    monkeypatch.setattr(ner, "spans_for", lambda text: spans)
    both = [Span(Kind.PERSON, 0, 2, 0.9, "ner"), Span(Kind.PHONE, 5, 10, 0.9, "rule")]
    monkeypatch.setattr(ner, "detect_with_ner", lambda text, known_names=(): both)
    ok, detail = ORIGINAL_NER_PROBE()
    assert ok and "PERSON" in detail and "PHONE" in detail and "ms" in detail
    monkeypatch.setattr(ner, "detect_with_ner", lambda text, known_names=(): both[:1])
    assert not ORIGINAL_NER_PROBE()[0]  # 전화를 못 찾았다
    monkeypatch.setattr(ner, "spans_for", lambda text: [])
    assert not ORIGINAL_NER_PROBE()[0]  # NER 이 아무것도 못 찾았다(모델이 일하지 않음)


NER_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "ner"


@pytest.mark.skipif(not NER_DIR.is_dir(), reason="이 PC 에 NER 모델 폴더가 없다")
def test_the_real_ner_model_loads_and_finds_the_synthetic_values(monkeypatch, fresh_ner):
    monkeypatch.setattr(settings, "privacy_ner_mode", "required")
    monkeypatch.setattr(settings, "privacy_ner_model_dir", str(NER_DIR))
    ok, detail = ORIGINAL_NER_PROBE()
    assert ok, detail


# ---------- 4: 전송 본문 ----------
def stub_run(monkeypatch, bodies, status="judged", case_id="b-total"):
    report = SimpleNamespace(
        records=[SimpleNamespace(case_id=case_id, status=status)],
        fakes={(case_id, 0): SimpleNamespace(bodies=bodies)},
    )
    monkeypatch.setattr(runner, "run_cases", lambda *a, **k: report)


def body(text="10월 지출 합계 알려줘", **over):
    base = {
        "model": settings.llm_model,
        "max_tokens": 1024,
        "system": "가계(정산) 담당",
        "messages": [{"role": "user", "content": text}],
    }
    base.update(over)
    return base


def pass_check(tmp_path):
    return preflight._fake_pass(make_input(tmp_path))[0]


def test_check_4_passes_for_a_clean_body_and_reports_the_estimated_input(tmp_path, monkeypatch):
    stub_run(monkeypatch, [body()])
    check, bodies, max_in = preflight._fake_pass(make_input(tmp_path))
    assert check.status == PASS and len(bodies) == 1 and max_in > usage.OVERHEAD_TOKENS
    assert "실제 전송 0회" in check.detail and "추정 입력 토큰 최대" in check.detail


@pytest.mark.parametrize(
    ("bad", "text"),
    [
        (body(system="x-api-key: abc 로 보낸다"), "키·인증 헤더"),
        (body(system="Authorization 헤더"), "키·인증 헤더"),
        (body("sk-ant-abcdefghijklmnop 를 써 줘"), "키·인증 헤더"),
        (body(f"키는 {CANARY} 야"), "키·인증 헤더"),
        (body(model="claude-sonnet-5-5"), "model"),
        # Agent 경로가 아닌 호출(답 검증)은 일반 상한, Agent 경로 호출은 천장을 넘으면 막는다
        (body(system=VERIFY_SYSTEM, max_tokens=settings.anthropic_max_tokens + 1), "max_tokens"),
        (body(max_tokens=preflight.AGENT_OUTPUT_CEILING + 1), "max_tokens"),
        (body(max_tokens=None), "max_tokens"),
        (body("남의 가족 지출은 77,777원이에요"), "비공개 문자열"),
        (body("연락처는 010-1234-5678 입니다"), "PHONE"),
    ],
)
def test_check_4_fails_for_each_kind_of_bad_body(tmp_path, monkeypatch, bad, text):
    stub_run(monkeypatch, [body(), bad])
    check = pass_check(tmp_path)
    assert check.status == FAIL and text in check.detail
    assert CANARY not in check.detail


def test_check_4_fails_without_bodies_or_when_a_case_did_not_finish(tmp_path, monkeypatch):
    stub_run(monkeypatch, [])
    assert "가로챈 요청 본문이 없다" in pass_check(tmp_path).detail
    stub_run(monkeypatch, [body()], status="error")
    assert pass_check(tmp_path).status == FAIL


def test_check_4_skips_private_strings_that_the_question_itself_contains(tmp_path, monkeypatch):
    """질문에 이미 있는 글이 본문에 있는 것은 노출이 아니다(예: 다른 가족을 묻는 질문)."""
    item = legacy("b-total")[0]
    needles, dropped = preflight._needles_of(item)
    assert "남의 가족" in needles and dropped == 0
    asked = item.case.model_copy(update={"question": item.case.question + " 남의 가족"})
    needles, dropped = preflight._needles_of(adapter.LegacyCase(asked, item.checks))
    assert "남의 가족" not in needles and dropped == 1


def test_check_4_fails_if_the_real_transport_function_is_ever_called(tmp_path, monkeypatch):
    """가짜 전송 함수를 끼우지 못한 길이 있다고 가정한다: 실제 전송 함수 자리의 감시 함수가 불리면 점검이 실패한다."""

    @contextmanager
    def not_installed(fake):
        yield fake  # 끼우지 않는다 -> 앱이 부르는 전송 함수는 감시 함수다

    monkeypatch.setattr(fake_model, "installed", not_installed)
    check = preflight._fake_pass(make_input(tmp_path))[0]
    assert check.status == FAIL
    assert "실제 전송 함수가 불렸다" in check.detail
    assert fake_model.FakeModel.record_bodies is False  # 스위치는 되돌아온다


def test_check_4_runs_the_app_path_for_real_and_never_touches_the_real_transport(
    tmp_path, isolated
):
    check, bodies, max_in = preflight._fake_pass(make_input(tmp_path))
    assert check.status == PASS, check.detail
    assert bodies and all(b["model"] == settings.llm_model for b in bodies)
    assert max_in > 0 and isolated == []
    assert transport.post_messages is not fake_model  # 끝나면 원래 자리로 돌아온다
    assert fake_model.FakeModel.record_bodies is False


# ---------- 4: Agent 경로 호출은 10000 토큰 천장, 그 밖의 호출은 일반 상한 ----------
def analysis_body(**over):
    """앱이 대화 분석(`analyze_recent_chat`)에서 보내는 본문의 모양: 분석 시스템 프롬프트 + 구조화 출력."""
    from app.features.family_chat.ai_service import ANALYSIS_SYSTEM

    base = body(
        "최근 대화를 정리해 줘",
        system=ANALYSIS_SYSTEM,
        max_tokens=10000,
        output_config={"format": {"type": "json_schema", "schema": {}}},
    )
    base.update(over)
    return base


def verify_body(**over):
    """답 검증 호출의 본문(Agent 경로가 아니다): 일반 상한(2048)으로 본다."""
    from app.features.ai_assistant.knowledge.verify import VERIFY_MAX_TOKENS, VERIFY_SYSTEM

    base = body("검증", system=VERIFY_SYSTEM, max_tokens=VERIFY_MAX_TOKENS)
    base.update(over)
    return base


def agent_body(path, **over):
    """확인된 Agent 호출 경로의 본문 모양(실제 시스템 프롬프트 머리말·고정 문구). path: main|family_chat|billing|schedule|analysis."""
    from app.features.ai_assistant.knowledge import rag_chat
    from app.features.schedule.agent import prompts as schedule_prompts

    if path == "analysis":
        return analysis_body(**over)
    systems = {
        "main": rag_chat.SYSTEM_PROMPT + "\n오늘은 …",
        "family_chat": preflight.FAMILY_CHAT_SYSTEM_PREFIX + " …",
        "billing": preflight.BILLING_SYSTEM_PREFIX + " 사용자 이름은 …",
        "schedule": schedule_prompts.CHAT_SYSTEM,
    }
    base = body("질문", system=systems[path], max_tokens=10000)
    if path == "schedule":
        base["output_config"] = {"format": {"type": "json_schema", "schema": {}}}
    base.update(over)
    return base


def test_the_pinned_agent_ceiling_equals_the_apps_default_setting():
    """앱의 Agent 상한 기본값이 바뀌면 이 시험이 실패해 사전 점검 천장을 사람이 다시 정하게 한다(조용히 커지지 않는다)."""
    from app.shared.config import Settings

    assert preflight.AGENT_OUTPUT_CEILING == Settings().agent_max_output_tokens == 10000
    assert settings.anthropic_max_tokens == 2048  # 나머지 호출의 기본 상한은 그대로다


def test_the_classifier_prefixes_match_the_real_system_prompts():
    """분류에 쓰는 고정 머리말이 실제 정산·소통·메인·일정 시스템 프롬프트와 어긋나면 이 시험이 실패한다."""
    from app.features.billing import agent as billing_agent
    from app.features.family_chat import agent as family_agent

    assert billing_agent.system_prompt("지민").startswith(preflight.BILLING_SYSTEM_PREFIX)
    assert family_agent.system_prompt().startswith(preflight.FAMILY_CHAT_SYSTEM_PREFIX)
    assert [preflight.agent_path_of(agent_body(p)) for p in preflight.AGENT_PATHS] == list(
        preflight.AGENT_PATHS
    )


def test_main_system_prompts_built_by_the_app_are_classified_as_main():
    from app.features.ai_assistant.knowledge import rag_chat

    for kwargs in ({}, {"with_agents": True}, {"with_agents": True, "with_web": True}):
        system = rag_chat.system_prompt(**kwargs)
        assert preflight.agent_path_of(body(system=system)) == "main"


def test_check_4_allows_the_six_agent_paths_up_to_the_ceiling_and_keeps_verify_at_the_default(
    tmp_path, monkeypatch
):
    for path in preflight.AGENT_PATHS:
        stub_run(monkeypatch, [body(), agent_body(path)])
        assert pass_check(tmp_path).status == PASS, path
    stub_run(monkeypatch, [body(), analysis_body(max_tokens=3000)])  # 예전 상한도 그대로 통과한다
    assert pass_check(tmp_path).status == PASS
    stub_run(monkeypatch, [agent_body("billing"), verify_body()])  # 정산 10000, 검증 2048
    assert pass_check(tmp_path).status == PASS


@pytest.mark.parametrize("path", ["main", "family_chat", "billing", "schedule", "analysis"])
def test_check_4_blocks_each_agent_path_above_the_ceiling(tmp_path, monkeypatch, path):
    stub_run(monkeypatch, [body(), agent_body(path, max_tokens=10001)])
    check = pass_check(tmp_path)
    assert check.status == FAIL and "상한(10000)" in check.detail
    stub_run(monkeypatch, [body(), agent_body(path, max_tokens=None)])
    assert pass_check(tmp_path).status == FAIL


@pytest.mark.parametrize(
    "bad",
    [
        verify_body(max_tokens=2049),  # 답 검증: 천장을 못 쓴다
        verify_body(max_tokens=4096),
        verify_body(max_tokens=10000),
        body(system="알 수 없는 일반 호출", max_tokens=4096),  # 미분류 일반 호출
        body(system="알 수 없는 일반 호출", max_tokens=10000),
        body(system="가계(정산) 담당", max_tokens=10000),  # 머리말이 다른 정산 비슷한 본문
        body(system="가족 채팅 담당 에이전트", max_tokens=3000),
        body(
            system="일정 담당", max_tokens=5000, output_config={"format": {}}
        ),  # 일정 프롬프트 아님
        {k: v for k, v in agent_body("main").items() if k != "system"},  # system 없음
        {
            k: v for k, v in agent_body("schedule").items() if k != "output_config"
        },  # 구조화 출력 아님
        {k: v for k, v in agent_body("analysis").items() if k != "output_config"},
    ],
)
def test_check_4_rejects_unclassified_calls_above_the_general_cap(tmp_path, monkeypatch, bad):
    """확인된 여섯 경로가 아닌 호출(미분류)은 Agent 천장을 받지 못하고 일반 상한(2048)을 넘으면 사전 점검이 실패한다."""
    bad = {**bad, "max_tokens": bad.get("max_tokens") or 10000}
    stub_run(monkeypatch, [body(), bad])
    check = pass_check(tmp_path)
    assert check.status == FAIL and "상한(2048)" in check.detail


def test_max_tokens_cap_is_per_call_path():
    ceiling = preflight.AGENT_OUTPUT_CEILING
    for path in preflight.AGENT_PATHS:
        assert preflight.max_tokens_cap(agent_body(path), 2048) == ceiling
    assert (
        preflight.max_tokens_cap(verify_body(), 2048) == 2048
    )  # Agent 경로가 아닌 호출은 일반 상한
    assert preflight.max_tokens_cap(body(system="알 수 없음"), 2048) == 2048  # 미분류


def test_the_general_cap_setting_never_raises_the_agent_ceiling(tmp_path, monkeypatch):
    """ANTHROPIC_MAX_TOKENS 를 크게 해도 Agent 천장은 그대로 10000 이다(예전 max(default, 천장)이면 올라갔다)."""
    monkeypatch.setattr(settings, "anthropic_max_tokens", 20000)
    assert preflight.max_tokens_cap(agent_body("billing"), 20000) == 10000
    assert preflight.AGENT_OUTPUT_CEILING == 10000
    stub_run(monkeypatch, [body(), agent_body("billing", max_tokens=12000)])
    check = pass_check(tmp_path)
    assert check.status == FAIL and "상한(10000)" in check.detail
    # 미분류·검증 호출은 일반 상한 설정을 그대로 따른다(일반 설정의 의미)
    assert preflight.max_tokens_cap(verify_body(), 20000) == 20000


def test_check_4_blocks_an_env_override_above_the_ceiling_and_accepts_a_lower_one(
    tmp_path, monkeypatch
):
    """환경변수로 Agent 상한을 천장보다 크게 올리면 사전 점검이 실패하고(조용히 커지지 않는다), 낮추면 통과한다."""
    stub_run(monkeypatch, [agent_body("billing", max_tokens=12000)])
    check = pass_check(tmp_path)
    assert check.status == FAIL and "상한(10000)" in check.detail
    stub_run(monkeypatch, [agent_body("billing", max_tokens=5000)])
    assert pass_check(tmp_path).status == PASS


def test_the_runtime_cost_gate_still_uses_the_request_body_max_tokens():
    """호출 직전 비용 검사(`usage`)는 이 분류와 무관하게 요청 본문의 max_tokens 를 그대로 쓴다(변경 없음)."""
    import inspect

    from evals.agent_eval import usage as usage_mod

    source = inspect.getsource(usage_mod)
    assert 'int(body["max_tokens"])' in source and "agent_path_of" not in source


def chat_03_input(tmp_path, **kw):
    from evals.agent_eval import case_files, dev_cases, dev_scripts

    items = [
        c
        for c in case_files.load_cases(dev_cases.CASES_DEV_PATH, "dev")
        if c.id == "s-dev-05-chat-03"
    ]
    assert len(items) == 1
    base = dict(
        split="dev",
        requested_ids=("s-dev-05-chat-03",),
        items=items,
        scripts=dev_scripts.scripts_for("dev"),
    )
    base.update(kw)
    return make_input(tmp_path, **base)


def test_check_4_passes_for_chat_03_through_the_real_app_path_and_sees_the_analysis_call(
    tmp_path,
):
    """회귀: 예전에는 분석 호출(3000)이 일괄 상한 2048 에 걸려 chat-03 이 항상 실패했다. Agent 경로 상한은 이제 공통 설정 10000 이다."""
    from app.features.ai_assistant.knowledge.verify import VERIFY_SYSTEM

    check, bodies, _ = preflight._fake_pass(chat_03_input(tmp_path))
    assert check.status == PASS, check.detail
    caps = [b["max_tokens"] for b in bodies]
    assert 10000 in caps and all(c <= 10000 for c in caps)
    assert any(preflight._is_analysis_body(b) and b["max_tokens"] == 10000 for b in bodies)
    assert all(b["max_tokens"] <= 2048 for b in bodies if b.get("system") == VERIFY_SYSTEM)


# ---------- 5·6: DB·네트워크 ----------
def test_check_5_fails_when_the_process_boundary_is_not_safe(tmp_path, monkeypatch, quick_body):
    def boom(root):
        raise env.UnsafeEnvironment("PostgreSQL 은 안 된다")

    monkeypatch.setattr(env, "check_process_boundary", boom)
    report = run_preflight(make_input(tmp_path))
    assert failed_numbers(report) == [5] and report.record is None
    assert report.checks[4].status == FAIL


def test_check_6_requires_exactly_one_allowed_host_and_blocked_outside_connections(
    tmp_path, monkeypatch, quick_body
):
    ok = run_preflight(make_input(tmp_path)).checks[5]
    assert ok.status in (PASS, WARN) and "api.anthropic.com" in ok.detail and "막힘" in ok.detail
    monkeypatch.setattr(real_gate, "REAL_HOSTS", ("api.anthropic.com", "evil.test"))
    report = run_preflight(make_input(tmp_path))
    assert failed_numbers(report) == [6]


def test_check_6_warns_about_proxy_variables_without_printing_their_values(
    tmp_path, monkeypatch, quick_body
):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret-pass@proxy.example:8080")
    check = run_preflight(make_input(tmp_path)).checks[5]
    assert check.status == WARN and "https_proxy" in check.detail.lower()
    assert "secret-pass" not in check.detail and os.environ["HTTPS_PROXY"].startswith("http://user")


def test_check_6_fails_if_a_grant_is_open_during_the_preflight(tmp_path, quick_body):
    from tests.agent_eval.runner_support import real_grant_for

    grant = real_grant_for(legacy("b-total"), run_id="x")
    with real_gate.real_grant_scope(grant):
        report = run_preflight(make_input(tmp_path))
    assert 6 in failed_numbers(report)


# ---------- 7: 사례 ----------
def test_check_7_lists_the_cases_and_rejects_missing_ids_split_mismatch_and_write_cases(
    tmp_path, quick_body
):
    report = run_preflight(make_input(tmp_path))
    assert report.checks[6].status == PASS and "b-total |" in report.checks[6].detail
    assert "읽기 전용 예" in report.checks[6].detail
    missing = run_preflight(
        make_input(tmp_path, requested_ids=("b-total", "nope"), missing_ids=("nope",))
    )
    assert 7 in failed_numbers(missing) and "존재하지 않는 사례 id" in missing.checks[6].detail
    mismatch = run_preflight(make_input(tmp_path, split="dev"))
    assert 7 in failed_numbers(mismatch) and "분할 불일치" in mismatch.checks[6].detail
    write = run_preflight(
        make_input(tmp_path, requested_ids=("b-write-propose",), items=legacy("b-write-propose"))
    )
    assert 7 in failed_numbers(write) and "쓰기 평가 사례" in write.checks[6].detail
    assert write.record is None


def test_check_7_rejects_a_case_with_a_seed_or_a_schedule_write_name():
    from tests.agent_eval.runner_support import new_case

    seeded = new_case("n-seed", setup={"seed": "x"})
    sched = new_case("n-sched", expect={"tools": {"forbidden": ["schedule.register"]}})
    assert "setup.seed" in preflight.reject_reason(seeded, "dev")
    assert "일정 쓰기" in preflight.reject_reason(sched, "dev")
    assert preflight.reject_reason(new_case("n-ok"), "dev") is None
    forbidding_a_billing_write = new_case(
        "n-neg", expect={"tools": {"forbidden": ["propose_add_expense"]}}
    )
    assert (
        preflight.reject_reason(forbidding_a_billing_write, "dev") is None
    )  # 금지만 한 사례는 읽기 전용이다
    requiring = new_case("n-req", expect={"tools": {"required": ["propose_add_expense"]}})
    assert "쓰기 도구를 기대" in preflight.reject_reason(requiring, "dev")


# ---------- 8: 비용 ----------
def test_the_main_loop_worst_is_cases_x_repeats_x_steps_plus_verify_x_call_cost():
    got = preflight.main_loop_worst("claude-haiku-5-5", 9, 2, 8000, 2048)
    assert got == 9 * 2 * (4 + 1) * call_cost("claude-haiku-5-5", 8000, 2048)
    assert preflight._max_steps() == 4  # 메인 도구 루프의 단계 상한(rag_chat.MAX_STEPS)


def test_check_8_prints_both_estimates_and_passes_under_the_approved_amount(tmp_path, quick_body):
    check = run_preflight(make_input(tmp_path)).checks[7]
    assert check.status == PASS
    assert (
        "기본 가정 추정" in check.detail
        and "메인 루프 기준 최악 상한(하위 Agent 호출 포함 안 함)" in check.detail
    )
    assert (
        "구조적 이론 최대(정보용, 거부 기준 아님)" in check.detail and "max_tokens" in check.detail
    )
    assert "넘으면 그 호출을 시작하지 않는다" in check.detail  # 하드 보장은 실행 중 호출 직전 검사
    assert "보장하지는 않는다" in check.detail  # 사전 점검 통과는 중간 중단 없음을 보장하지 않는다
    assert "보수적 최악" not in check.detail  # 이름을 정직하게 바꿨다


def test_check_8_rejects_a_worst_case_above_the_approved_amount_even_if_the_basic_estimate_fits(
    tmp_path, quick_body
):
    approve = D("0.005")  # 기본 추정 0.0042 <= 0.005 < 메인 루프 기준 최악 상한(검증 1회 포함)
    report = run_preflight(make_input(tmp_path, approve=approve))
    basic = D("0.0042")
    assert basic <= approve and failed_numbers(report) == [8] and report.record is None
    assert "승인 금액보다 크다" in report.checks[7].detail
    assert cli._preflight_code(report) == cli.OVER_BUDGET


def test_check_8_follows_the_measured_body_size_when_it_is_larger_than_the_assumption(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        preflight, "_fake_pass", lambda inp: (Check(4, "본문", PASS, "시험용"), [], 40_000)
    )
    detail = run_preflight(make_input(tmp_path)).checks[7].detail
    assert "입력 40000 토큰" in detail


def test_analysis_calls_are_priced_with_the_agent_cap_in_the_worst_case(tmp_path, quick_body):
    model = "claude-haiku-5-5"
    item = chat_03_input(tmp_path).items
    assert preflight.expected_analysis_calls(item) == 1
    assert preflight.expected_analysis_calls(legacy("b-total")) == 0  # 분석을 기대하지 않는 사례
    got = preflight.analysis_call_worst(model, 1, 2, 12450, 2048)
    assert got == 2 * call_cost(model, 12450, 10000) > 2 * call_cost(model, 12450, 2048)
    extra = preflight.structural_analysis_extra(model, 1, 1, 12450, 2048)
    per_call = call_cost(model, 12450, 10000) - call_cost(model, 12450, 2048)
    assert extra == preflight.structural_analysis_calls() * per_call
    assert preflight.structural_analysis_calls() == 12  # (MAX_STEPS-1) x 하위 Agent 단계 4


def test_check_8_adds_the_analysis_call_to_the_gate_for_chat_03_and_not_for_other_cases(
    tmp_path, quick_body
):
    plain = run_preflight(make_input(tmp_path)).checks[7].detail
    assert "대화 분석 호출" not in plain  # 분석을 기대하지 않는 사례는 이전 출력과 같다
    detail = run_preflight(chat_03_input(tmp_path)).checks[7].detail
    assert "대화 분석 호출 1회" in detail and "출력 10000 토큰" in detail
    only_loop = preflight.main_loop_worst(settings.llm_model, 1, 1, 8000, 10000)
    ana = preflight.analysis_call_worst(settings.llm_model, 1, 1, 8000, 10000)
    assert f"사전 거부 기준값 {format(only_loop + ana, 'f')} USD" in detail


def _gate_of(detail):
    import re

    return D(re.search(r"사전 거부 기준값 ([0-9.]+) USD", detail).group(1))


def test_check_8_prices_the_worst_case_with_the_agent_output_cap(tmp_path, quick_body, monkeypatch):
    """Agent 경로 상한(공통 설정)이 사전 거부 기준값에 그대로 반영되고, 일반 상한과 구분해 보여 준다."""
    detail = run_preflight(make_input(tmp_path)).checks[7].detail
    assert "출력 10000 토큰[max_tokens]" in detail
    assert "Agent 경로(메인·소통·일정·정산·대화 분석) 10000(허용 천장 10000)" in detail
    assert "그 밖의 호출 2048(일반 상한)" in detail
    gate_10k = _gate_of(detail)
    monkeypatch.setattr(settings, "agent_max_output_tokens", 2048)
    low = run_preflight(make_input(tmp_path)).checks[7].detail
    assert "출력 2048 토큰[max_tokens]" in low
    assert (
        _gate_of(low) < gate_10k
    )  # 상한이 크면 거부 기준값이 커진다(승인액은 최대 사용 가능량 기준)


def test_check_8_rejects_when_the_approval_only_covered_the_old_output_cap(
    tmp_path, quick_body, monkeypatch
):
    """승인액이 예전 상한(2048) 기준 최악 비용은 덮지만 10000 기준에는 모자라면 거부한다(비용 게이트가 완화되지 않았다)."""
    detail = run_preflight(make_input(tmp_path, approve=D("5"))).checks[7].detail
    gate_10k = _gate_of(detail)
    monkeypatch.setattr(settings, "agent_max_output_tokens", 2048)
    gate_2k = _gate_of(run_preflight(make_input(tmp_path, approve=D("5"))).checks[7].detail)
    assert gate_2k < gate_10k
    approve = (gate_2k + gate_10k) / 2
    assert run_preflight(make_input(tmp_path, approve=approve)).checks[7].status == PASS
    monkeypatch.setattr(settings, "agent_max_output_tokens", 10000)
    report = run_preflight(make_input(tmp_path, approve=approve))
    assert report.checks[7].status == FAIL and "승인 금액보다 크다" in report.checks[7].detail


def test_check_8_rejects_a_model_missing_from_the_price_table(tmp_path, quick_body):
    report = run_preflight(make_input(tmp_path, model="claude-unknown-9"))
    assert 8 in failed_numbers(report) and "단가표에 없는 모델" in report.checks[7].detail
    assert set(PRICES) >= {"claude-haiku-5-5"}


# ---------- 9: 결과 위치 ----------
def test_check_9_requires_the_default_folder_a_free_run_id_and_git_exclusion(
    tmp_path, monkeypatch, quick_body
):
    assert run_preflight(make_input(tmp_path)).checks[8].status == PASS
    elsewhere = run_preflight(make_input(tmp_path, results_root=tmp_path / "other"))
    assert failed_numbers(elsewhere) == [9] and "기본 결과 폴더 밖" in elsewhere.checks[8].detail
    (tmp_path / "results" / "pf-1").mkdir(parents=True)
    taken = run_preflight(make_input(tmp_path))
    assert failed_numbers(taken) == [9] and "이미 있다" in taken.checks[8].detail
    (tmp_path / "results" / "pf-1").rmdir()
    monkeypatch.setattr(
        preflight, "_git_ignored", lambda p: (False, "Git 추적에서 제외되지 않는다")
    )
    tracked = run_preflight(make_input(tmp_path))
    assert failed_numbers(tracked) == [9] and "제외되지 않았거나" in tracked.checks[8].detail
    monkeypatch.setattr(preflight, "_git_ignored", lambda p: (None, "git 을 실행할 수 없다"))
    assert failed_numbers(run_preflight(make_input(tmp_path))) == [
        9
    ]  # 확인할 수 없으면 실패(안전한 쪽)


def test_the_default_results_folder_is_really_ignored_by_git():
    real_results = Path(cli.__file__).parent / "results" / "pf-probe"
    ignored, why = preflight._git_ignored(real_results)
    assert ignored is True, why


# ---------- CLI: 실패하면 --real 이 시작되지 않는다 ----------
@pytest.fixture
def transport_fake(monkeypatch):
    """CLI 시험이 실제 경로에서 쓰는 가짜 전송 함수. 사전 점검이 실패하면 이 함수는 한 번도 불리지 않는다."""
    fake = fake_model.FakeModel(fake_model.script_for(legacy("b-total")[0]))
    monkeypatch.setattr(transport, "post_messages", fake)
    return fake


def run_cli(argv, tmp_path, results="results"):
    lines: list[str] = []
    code = cli.main([*argv, "--results-dir", str(tmp_path / results)], out=lines.append)
    return code, "\n".join(lines)


def real_argv(*extra, case="b-total", approve="1", mode="--real"):
    return [mode, "--approve-usd", approve, "--case", case, *extra]


def test_the_preflight_flag_passes_cleanly_and_makes_no_call_and_leaves_nothing(
    tmp_path, transport_fake, isolated, caplog
):
    with caplog.at_level(logging.DEBUG):
        code, text = run_cli(real_argv(mode="--preflight"), tmp_path)
    assert code == 0, text
    assert text.count("[통과]") + text.count("[경고]") == 9 and "모두 통과" in text
    assert transport_fake.calls == 0 and isolated == []
    assert not (tmp_path / "results").exists()  # 점검은 아무것도 저장하지 않는다
    assert CANARY not in text and CANARY not in caplog.text
    assert real_gate.real_grant() is None


FAILING = [
    ("key", 1, {"key": ""}, []),
    ("model", 2, {}, ["--model", "claude-sonnet-5-5"]),
    ("ner", 3, {"ner": True}, []),
    ("body", 4, {"body": True}, []),
    ("boundary", 5, {"boundary": True}, []),
    ("network", 6, {"network": True}, []),
    ("cases", 7, {}, ["--case", "b-write-propose"]),
    ("results", 9, {"git": True}, []),
]


@pytest.mark.parametrize(("name", "number", "patches", "extra"), FAILING)
def test_when_any_check_fails_real_never_starts_and_the_transport_is_never_called(
    name, number, patches, extra, tmp_path, monkeypatch, transport_fake, isolated, caplog
):
    if "key" in patches:
        monkeypatch.setattr(settings, "anthropic_api_key", patches["key"])
    if patches.get("ner"):
        monkeypatch.setattr(preflight, "ner_probe", lambda: (False, "NER 로드·추론 실패(X)"))
    if patches.get("body"):
        monkeypatch.setattr(
            preflight, "_fake_pass", lambda inp: (Check(4, "본문", FAIL, "본문에 문제"), [], 0)
        )
    if patches.get("boundary"):
        monkeypatch.setattr(
            env,
            "check_process_boundary",
            lambda root: (_ for _ in ()).throw(env.UnsafeEnvironment("운영 DB")),
        )
    if patches.get("network"):
        monkeypatch.setattr(real_gate, "REAL_HOSTS", ("api.anthropic.com", "evil.test"))
    if patches.get("git"):
        monkeypatch.setattr(preflight, "_git_ignored", lambda p: (False, "추적됨"))
    argv = real_argv()
    if extra[:1] == ["--case"]:
        argv = real_argv(case=extra[1])
    elif extra:
        argv = [*argv, *extra]
    with caplog.at_level(logging.DEBUG):
        code, text = run_cli(argv, tmp_path)
    assert code != 0 and "[실패]" in text and "실제 호출을 시작하지 않는다" in text, text
    assert f" {number}. [실패]" in text
    assert transport_fake.calls == 0 and isolated == []  # 전송 함수 호출 횟수 0
    assert not (tmp_path / "results").exists() and real_gate.real_grant() is None
    assert CANARY not in text and CANARY not in caplog.text


def test_the_same_failure_gives_a_nonzero_exit_code_for_the_preflight_flag_too(
    tmp_path, monkeypatch, transport_fake
):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    code, text = run_cli(real_argv(mode="--preflight"), tmp_path)
    assert code == cli.REFUSED and "[실패]" in text and "ANTHROPIC_API_KEY" in text


def test_a_worst_case_above_the_approved_amount_stops_real_with_the_over_budget_code(
    tmp_path, transport_fake
):
    code, text = run_cli(
        real_argv(approve="0.005"), tmp_path
    )  # 기본 추정은 통과, 메인 루프 기준 최악 상한은 초과
    assert (
        code == cli.OVER_BUDGET and "메인 루프 기준 최악 상한" in text and transport_fake.calls == 0
    )
    assert not (tmp_path / "results").exists()


def test_the_nine_case_real_run_is_refused_before_any_call_when_the_approval_misses_the_10000_cap(
    tmp_path, transport_fake
):
    """승인액이 10000 상한 기준 사전 거부 기준값에 모자라면 `--real` 도 호출 0회로 거부한다(승인액 미달 → 실제 호출 거부)."""
    argv = ["--real", "--split", "dev", "--dev-file", str(DEV_FILE), "--approve-usd", "0.20"]
    for case_id in PILOT_NINE:
        argv += ["--case", case_id]
    code, text = run_cli(argv, tmp_path)
    assert code == cli.OVER_BUDGET and "메인 루프 기준 최악 상한" in text
    assert transport_fake.calls == 0 and real_gate.real_grant() is None
    assert not (tmp_path / "results").exists()


def test_a_real_run_with_a_results_dir_outside_the_default_folder_is_refused(
    tmp_path, transport_fake
):
    code, text = run_cli(real_argv(), tmp_path, results="elsewhere")
    assert code == cli.REFUSED and "기본 결과 폴더 밖" in text and transport_fake.calls == 0
    assert not (tmp_path / "elsewhere").exists()


def test_a_real_run_with_an_existing_run_id_folder_is_refused_before_any_call(
    tmp_path, transport_fake
):
    (tmp_path / "results" / "dup-1").mkdir(parents=True)
    code, text = run_cli(real_argv("--run-id", "dup-1"), tmp_path)
    assert code == cli.REFUSED and "이미 있다" in text and transport_fake.calls == 0


def test_an_unknown_case_id_is_a_table_row_for_the_preflight_flag(tmp_path, transport_fake):
    code, text = run_cli(real_argv(case="nope", mode="--preflight"), tmp_path)
    assert code == cli.REFUSED and "존재하지 않는 사례 id" in text and transport_fake.calls == 0


def test_a_passing_real_run_starts_only_after_the_preflight_and_spends_the_grant(
    tmp_path, transport_fake
):
    code, text = run_cli(real_argv("--run-id", "ok-1"), tmp_path)
    assert code == 0, text
    assert text.index("사전 점검 결과: 모두 통과") < text.index("통과 1")
    assert transport_fake.calls == 2 and real_gate.real_grant() is None
    assert (tmp_path / "results" / "ok-1" / "manifest.json").is_file()


# ---------- 파일럿 대상 사전 확인(실호출 없이) ----------
def test_the_one_case_connection_test_passes_the_preflight(tmp_path, transport_fake):
    code, text = run_cli(
        [
            "--preflight", "--split", "dev", "--dev-file", str(DEV_FILE),
            "--approve-usd", "0.05", "--case", PILOT_ONE[0],
        ],
        tmp_path,
    )  # fmt: skip
    assert code == 0, text
    assert "s-dev-01-routing-01" in text and "읽기 전용 예" in text and transport_fake.calls == 0


def test_the_nine_case_pilot_is_rejected_at_020_dollars_with_the_10000_agent_cap_and_passes_with_a_larger_approval(
    tmp_path, transport_fake
):
    """2026-11-25: 출력 상한이 10000 이 되면 같은 9건의 사전 거부 기준값이 커져 예전 파일럿 승인액 $0.20 으로는 시작할 수 없다(승인액은 최대 사용 가능량 기준).
    게이트를 풀지 않고 승인액을 올려야 통과한다."""
    argv = ["--preflight", "--split", "dev", "--dev-file", str(DEV_FILE)]
    for case_id in PILOT_NINE:
        argv += ["--case", case_id]
    code, text = run_cli([*argv, "--approve-usd", "0.20"], tmp_path)
    assert code != 0 and "사전 거부 기준값" in text and "0.20" in text
    assert transport_fake.calls == 0
    code, text = run_cli([*argv, "--approve-usd", "0.35"], tmp_path)
    assert code == 0, text
    assert transport_fake.calls == 0


def test_the_nine_case_pilot_passes_the_preflight_within_the_total_cap_of_020_dollars(
    tmp_path, transport_fake, monkeypatch
):
    """파일럿 당시 구성(Agent 출력 상한 2048)의 회귀: 같은 조건에서는 예전처럼 $0.20 안에서 통과한다."""
    monkeypatch.setattr(settings, "agent_max_output_tokens", 2048)
    argv = ["--preflight", "--split", "dev", "--dev-file", str(DEV_FILE), "--approve-usd", "0.20"]
    for case_id in PILOT_NINE:
        argv += ["--case", case_id]
    code, text = run_cli(argv, tmp_path)
    assert code == 0, text
    for case_id in PILOT_NINE:
        assert f"{case_id} |" in text
    assert text.count("읽기 전용 예") == 9 and "읽기 전용 아니오" not in text
    assert transport_fake.calls == 0
    loop = [line for line in text.splitlines() if "메인 루프 기준 최악 상한" in line][0]
    value = D(loop.split("(하위 Agent 호출 포함 안 함) ")[1].split(" USD")[0])
    assert 0 < value <= D("0.20")  # 파일럿 합계 상한 안에서 시작할 수 있다(사전 거부 기준)
    theory = [line for line in text.splitlines() if "구조적 이론 최대" in line][0]
    theory_value = D(theory.split("거부 기준 아님) ")[1].split(" USD")[0])
    assert theory_value > D("0.20") > value  # 정보용: 거부 기준이 아니다(이 수치로 거부하지 않았다)
    assert real_gate.check_request(approve_usd="0.20", split="dev", case_ids=PILOT_NINE) == D(
        "0.20"
    )


def test_check_4_relaxes_family_expense_titles_only_for_a_billing_case_with_a_billing_call():
    from tests.agent_eval.runner_support import new_case

    case = new_case("n-bill", agent_path="billing", setup={"as_user": "수진"})
    strict, _ = preflight._needles_of(case, relax=False)
    relaxed, _ = preflight._needles_of(case, relax=True)
    assert set(runner.FAMILY_EXPENSE_TITLES) & set(strict)
    assert not set(runner.FAMILY_EXPENSE_TITLES) & set(relaxed)


def test_the_detector_input_is_cut_into_chunks_below_the_ner_limit():
    text = "\n".join(["가" * 500] * 20 + ["나" * 7000])
    chunks = preflight._chunks(text)
    assert chunks and all(len(c) <= preflight.DETECT_CHUNK_CHARS for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")
    assert preflight.DETECT_CHUNK_CHARS < 8000  # app.shared.privacy.ner.MAX_INPUT_CHARS
