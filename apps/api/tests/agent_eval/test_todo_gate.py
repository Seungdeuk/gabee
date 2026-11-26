"""할 일 라우팅 회귀 사례 2건의 제한적 실호출 허용 시험(L0, 실제 호출 0회). 일반화 사례(#523, `test_gen_gate.py`)와 같은 구조다.

허용: 커밋된 `cases_todo_routing.json` 의 `s-todo-01-family-only-01`·`s-todo-02-tab-only-01` 두 사례만(정확한 경로·id·내용 해시·고정값·코드 정의 일치).
공식 dev 36건과 일반화 5건의 허용 규칙은 그대로이고, 위장·변조·미커밋·허용 목록 밖 사례와 val·test·all 의 실호출은 계속 거부한다.
사전 점검(7번)·`cli._execute`·러너의 허가 확인이 같은 원본 검증(`runner.verify_committed`·`verify_dev_source`)을 쓴다.

주의: 커밋 대조(`_require_head_clean`)는 파일이 HEAD 와 같아야 하므로 이 시험은 사례·고정값 파일이 커밋된 뒤에 통과한다(미커밋이면 거부가 정상 동작이다).
"""

import json
from datetime import date, timedelta
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_eval import (
    approved_sets,
    case_files,
    cli,
    dev_cases,
    dev_scripts,
    gen_cases,
    preflight,
    real_gate,
    runner,
    todo_routing_cases,
    todo_routing_scripts,
)
from evals.agent_eval.real_gate import real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions
from evals.agent_eval.seeds import data as seed
from tests.agent_eval.runner_support import new_case, real_grant_for

OFFICIAL = dev_cases.CASES_DEV_PATH
GEN = gen_cases.GEN_PATH
TODO = todo_routing_cases.PATH
IDS = [spec[0] for spec in todo_routing_cases.SPECS]
FAMILY, TAB = IDS


@pytest.fixture(scope="module")
def todo_items():
    return case_files.load_cases(TODO, "dev")


@pytest.fixture(scope="module")
def gen_items():
    return case_files.load_cases(GEN, "dev")


@pytest.fixture(scope="module")
def official_items():
    return case_files.load_cases(OFFICIAL, "dev")


# ---------- 허용 ----------
def test_the_two_committed_routing_cases_are_accepted(todo_items):
    assert (
        [c.id for c in todo_items] == IDS == ["s-todo-01-family-only-01", "s-todo-02-tab-only-01"]
    )
    runner.verify_committed(todo_items, "dev")
    runner.verify_dev_source(TODO, todo_items)
    assert set(runner.committed_todo_rows()) == set(IDS)


def test_a_real_grant_for_the_routing_cases_passes_the_runner_gate(todo_items):
    """실제 실행 쪽 검증: 허가가 있고 사례가 커밋된 사례와 같으면 러너의 허가 확인을 통과한다(호출은 하지 않는다)."""
    options = RunOptions("r", mode="real", approved_usd=D("1"))
    with real_grant_scope(real_grant_for(todo_items)):
        grant = runner._check_real_grant(todo_items, todo_items, IDS, options)
    assert grant is not None


def test_the_preflight_case_check_accepts_them_and_uses_the_same_rule(todo_items):
    inp = SimpleNamespace(
        missing_ids=(), requested_ids=tuple(IDS), items=todo_items, split="dev", source_file=TODO
    )
    check = preflight._check_cases(inp)
    assert check.no == 7 and check.status == preflight.PASS, check.detail


def test_the_fake_scripts_for_the_file_are_found_only_for_that_exact_path(tmp_path):
    assert set(dev_scripts.scripts_for("dev", TODO)) == set(IDS)
    copy = tmp_path / "cases_todo_routing.json"
    copy.write_bytes(TODO.read_bytes())
    assert set(dev_scripts.scripts_for("dev", copy)) != set(
        IDS
    )  # 같은 내용의 다른 경로는 공식 대본(이 사례의 대본 없음)
    assert set(dev_scripts.scripts_for("dev", GEN)) == {spec[0] for spec in gen_cases.SPECS}
    assert len(dev_scripts.scripts_for("dev")) == 36  # 공식 dev 대본 집합은 그대로다
    assert todo_routing_scripts.SCRIPTS.keys() == set(IDS)


# ---------- 기존 허용 규칙은 그대로 ----------
def test_official_dev_cases_are_still_accepted_without_reading_the_new_files(
    official_items, monkeypatch
):
    def never(*a, **k):
        raise AssertionError("공식 dev 검증이 합성 사례 파일을 읽었다")

    monkeypatch.setattr(runner, "committed_todo_rows", never)
    monkeypatch.setattr(runner, "committed_gen_rows", never)
    runner.verify_committed(official_items, "dev")
    runner.verify_dev_source(OFFICIAL, official_items)
    assert len(official_items) == 36


def test_generalization_cases_are_still_accepted_without_reading_the_routing_files(
    gen_items, monkeypatch
):
    def never(*a, **k):
        raise AssertionError("일반화 검증이 라우팅 회귀 파일을 읽었다")

    monkeypatch.setattr(runner, "committed_todo_rows", never)
    runner.verify_committed(gen_items, "dev")
    runner.verify_dev_source(GEN, gen_items)
    assert len(gen_items) == 5


def test_the_official_generalization_and_routing_id_sets_are_pairwise_disjoint(
    official_items, gen_items, todo_items
):
    official = {c.id for c in official_items}
    gen = {c.id for c in gen_items}
    todo = {c.id for c in todo_items}
    assert not official & gen and not official & todo and not gen & todo
    assert [s.key for s in approved_sets.all_sets()] == [
        "gen",
        "todo_routing",
    ]  # 허용 목록은 코드의 두 항목뿐


# ---------- 거부 ----------
def test_a_tampered_routing_case_is_refused(todo_items):
    changed = todo_items[0].model_copy(update={"question": todo_items[0].question + " (바꿈)"})
    with pytest.raises(RunnerRefused, match="다르다"):
        runner.verify_committed([changed, todo_items[1]], "dev")
    with real_grant_scope(real_grant_for([changed])):
        with pytest.raises(RunnerRefused, match="다르다"):
            runner._check_real_grant(
                [changed],
                [changed],
                [changed.id],
                RunOptions("r", mode="real", approved_usd=D("1")),
            )


def test_a_case_outside_the_allow_list_is_refused():
    for case_id in ("s-todo-03-extra-01", "s-todo-01-family-only-02", "s-other-01"):
        with pytest.raises(RunnerRefused, match="목록에 없는"):
            runner.verify_committed([new_case(case_id, split="dev")], "dev")


def test_an_uncommitted_or_modified_routing_file_is_refused(todo_items, monkeypatch):
    def dirty(paths):
        raise RunnerRefused("기준 사례 파일이 HEAD 커밋과 다르다(미커밋)")

    monkeypatch.setattr(runner, "_require_head_clean", dirty)
    with pytest.raises(RunnerRefused, match="HEAD"):
        runner.verify_committed(todo_items, "dev")


def test_the_head_check_covers_both_the_case_file_and_the_pins_file(todo_items, monkeypatch):
    seen: list[Path] = []

    def spy(paths):
        seen.extend(Path(p) for p in paths)

    monkeypatch.setattr(runner, "_require_head_clean", spy)
    runner.verify_committed(todo_items, "dev")
    resolved = {p.resolve() for p in seen}
    assert {
        TODO.resolve(),
        todo_routing_cases.PINS_PATH.resolve(),
    } <= resolved  # 사례 파일과 고정값 파일 모두 HEAD 와 대조한다
    assert (
        GEN.resolve() not in resolved and gen_cases.PINS_PATH.resolve() not in resolved
    )  # 일반화 파일은 읽지 않는다


def test_pin_mismatches_are_refused(tmp_path):
    rows = json.loads(TODO.read_text("utf-8"))
    pins = json.loads(todo_routing_cases.PINS_PATH.read_text("utf-8"))
    cases_file = tmp_path / "cases.json"
    pins_file = tmp_path / "pins.json"

    def run(rows_, pins_):
        cases_file.write_text(json.dumps(rows_, ensure_ascii=False, indent=1) + "\n", "utf-8")
        pins_file.write_text(json.dumps(pins_, ensure_ascii=False, indent=1) + "\n", "utf-8")
        return todo_routing_cases.check_pins(cases_file, pins_file)

    assert run(rows, pins) == []
    edited = json.loads(json.dumps(rows))
    edited[0]["question"] += " 바꿈"
    assert any("해시" in p for p in run(edited, pins))
    assert any("동결" in p for p in run(rows, {**pins, "frozen_before_any_model_output": False}))
    assert any("사례 수" in p for p in run(rows[:1], pins))
    wrong = json.loads(json.dumps(pins))
    wrong["cases"][1]["case_sha256"] = "0" * 64
    assert any("해시" in p for p in run(rows, wrong))
    # 해시를 파일에 맞춰 같이 바꿔도(고정값까지 바꿈) 코드의 사례 정의와 다르면 거부한다
    forged_rows = json.loads(json.dumps(rows))
    forged_rows[1]["expect"]["tools"]["forbidden"] = []
    forged_pins = json.loads(json.dumps(pins))
    forged_pins["cases_file_sha256"] = todo_routing_cases.file_sha256(
        (json.dumps(forged_rows, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    )
    forged_pins["cases"][1]["case_sha256"] = todo_routing_cases.case_sha256(forged_rows[1])
    assert any("정의" in p for p in run(forged_rows, forged_pins))


def test_the_gate_refuses_when_the_pins_do_not_match(todo_items, monkeypatch):
    monkeypatch.setattr(
        todo_routing_cases, "check_pins", lambda *a, **k: ["사례 파일 해시가 고정값과 다르다"]
    )
    with pytest.raises(RunnerRefused, match="고정값"):
        runner.verify_committed(todo_items, "dev")


def test_a_file_whose_ids_differ_from_the_allow_list_is_refused_even_if_the_pins_pass(
    todo_items, monkeypatch
):
    """허용 id 목록은 고정값 검사와 별도로 본다(고정값 검사가 통과하도록 꾸며도 파일의 id 집합이 목록과 다르면 거부한다)."""
    extra = new_case("s-todo-03-extra-01", split="dev")
    monkeypatch.setattr(case_files, "load_cases", lambda path, split: [*todo_items, extra])
    monkeypatch.setattr(todo_routing_cases, "check_pins", lambda *a, **k: [])
    with pytest.raises(RunnerRefused, match="허용 목록과 다르다"):
        runner.committed_todo_rows()


def test_an_id_overlap_with_official_or_other_approved_cases_is_refused(todo_items, monkeypatch):
    official_row = {"id": IDS[0]}
    monkeypatch.setattr(runner, "_official_dev_ids", lambda: [official_row])
    with pytest.raises(RunnerRefused, match="공식 dev 사례 id 와 겹친다"):
        runner.committed_todo_rows()
    monkeypatch.undo()
    real_sets = approved_sets.all_sets()
    gen_like = [
        s if s.key != "gen" else s.__class__(**{**s.__dict__, "ids": s.ids | {IDS[0]}})
        for s in real_sets
    ]
    monkeypatch.setattr(approved_sets, "all_sets", lambda: tuple(gen_like))
    with pytest.raises(RunnerRefused, match="다른 허용 사례 파일의 id 와 겹친다"):
        runner.committed_todo_rows()


def test_a_disguised_file_wrong_path_or_mixed_cases_are_refused(
    todo_items, gen_items, official_items, tmp_path
):
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(TODO.read_bytes())
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(copy, todo_items)  # 같은 내용의 다른 경로
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(OFFICIAL, todo_items)  # 공식 dev 파일 경로에 라우팅 사례
    with pytest.raises(RunnerRefused, match="사례 파일에는 일반화 사례"):
        runner.verify_dev_source(
            GEN, todo_items
        )  # 일반화 파일 경로에 라우팅 사례(그 파일은 일반화 사례만 담는다)
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(TODO, gen_items)  # 라우팅 파일 경로에 일반화 사례(일반화 쪽 규칙)
    with pytest.raises(RunnerRefused, match="사례 파일에는 할 일 라우팅 회귀 사례"):
        runner.verify_dev_source(TODO, [*todo_items, official_items[0]])  # 라우팅 파일에 공식 사례
    with pytest.raises(RunnerRefused, match="사례 파일에는 일반화 사례"):
        runner.verify_dev_source(GEN, [*gen_items, todo_items[0]])  # 일반화 파일에 라우팅 사례
    check = preflight._check_cases(
        SimpleNamespace(
            missing_ids=(),
            requested_ids=tuple(IDS),
            items=todo_items,
            split="dev",
            source_file=copy,
        )
    )
    assert check.status == preflight.FAIL and "허용된 사례 파일" in check.detail


# ---------- 실제 CLI 실행 경로: 허용되지 않은 --dev-file 은 허가 발급·네트워크 호출 전에 거부 ----------
def _real_argv(dev_file, split="dev", repeat="3", approve="0.1", cases=IDS):
    return [
        "--real",
        "--approve-usd",
        approve,
        "--split",
        split,
        "--dev-file",
        str(dev_file),
        "--repeat",
        repeat,
        *[a for c in cases for a in ("--case", c)],
    ]


@pytest.fixture
def no_network(monkeypatch):
    """실제 호출·허가 발급이 한 번이라도 일어나면 시험을 실패시킨다."""
    import httpx

    from app.shared.config import settings
    from app.shared.llm import transport

    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-todo-gate-0001")
    sent: list[str] = []

    def boom(*a, **k):
        sent.append("call")
        raise AssertionError("실제 호출을 시도했다")

    def no_grant(*a, **k):
        sent.append("grant")
        raise AssertionError("허가가 발급됐다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    monkeypatch.setattr(real_gate, "issue_grant", no_grant)
    return sent


def test_the_cli_execute_path_refuses_a_disallowed_dev_file_before_any_grant_or_call(
    tmp_path, no_network
):
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(TODO.read_bytes())
    args = cli.build_parser().parse_args(_real_argv(copy))
    plan = cli.make_plan(args)
    messages: list[str] = []
    code = cli._execute(args, plan, messages.append)
    assert code == cli.REFUSED
    assert any("허용된 사례 파일" in m for m in messages), messages
    assert no_network == []


def test_the_full_real_cli_stops_at_the_preflight_for_a_disallowed_dev_file(tmp_path, no_network):
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(TODO.read_bytes())
    lines: list[str] = []
    code = cli.main(_real_argv(copy), out=lines.append)
    assert code != cli.OK
    assert any("허용된 사례 파일" in line for line in lines)
    assert no_network == []


def test_the_runner_checks_case_content_and_the_cli_checks_the_file_path(todo_items, tmp_path):
    """역할 구분: 러너는 사례 **내용**만 대조하고, 경로는 CLI(`verify_dev_source`)가 맡는다."""
    options = RunOptions("r", mode="real", approved_usd=D("1"))
    with real_grant_scope(real_grant_for(todo_items)):
        assert runner._check_real_grant(todo_items, todo_items, IDS, options) is not None
    copy = tmp_path / "other_path.json"
    copy.write_bytes(TODO.read_bytes())
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(copy, todo_items)


# ---------- val·test·all 은 계속 금지, 한도 불변 ----------
@pytest.mark.parametrize("split", ["val", "test", "all"])
def test_val_test_all_real_calls_stay_forbidden_even_with_the_routing_file(split):
    assert real_gate.ALLOWED_SPLITS == ("legacy", "dev")
    args = cli.build_parser().parse_args(_real_argv(TODO, split=split, cases=[FAMILY]))
    with pytest.raises(cli.Refusal):
        cli.make_plan(args)
    with pytest.raises(RunnerRefused):
        runner.committed_rows(split)
    # 허용 파일이라도 val 분할로 사례를 위장해 통과시킬 수 없다
    disguised = new_case(FAMILY, split="val")
    with pytest.raises(RunnerRefused):
        runner.verify_committed([disguised], "val")


def test_case_count_repeat_and_cost_limits_are_unchanged():
    # 2건 x 반복 3 = 6회는 기존 한도 안이다
    real_gate.check_request(
        approve_usd=D("0.1"), split="dev", case_ids=IDS, repeat=3, require_env=False
    )
    with pytest.raises(real_gate.RealGateRefused):  # 반복 상한(3)은 그대로
        real_gate.check_request(
            approve_usd=D("0.1"), split="dev", case_ids=IDS, repeat=4, require_env=False
        )
    with pytest.raises(real_gate.RealGateRefused):  # 명시한 사례 수 상한(10)은 그대로
        real_gate.check_request(
            approve_usd=D("0.1"),
            split="dev",
            case_ids=[f"x-{i}" for i in range(11)],
            repeat=1,
            require_env=False,
        )
    with pytest.raises(real_gate.RealGateRefused):  # 사례를 명시하지 않은 호출은 그대로 거부
        real_gate.check_request(
            approve_usd=D("0.1"), split="dev", case_ids=[], repeat=1, require_env=False
        )
    assert real_gate.MAX_REAL_CASES == 10 and real_gate.MAX_REAL_REPEAT == 3


def test_the_routing_case_file_is_not_a_hidden_val_or_test_path():
    assert TODO.name == "cases_todo_routing.json"
    assert "val" not in TODO.stem and "test" not in TODO.stem


# ---------- 합성 시드의 답변 근거(읽기 전용 확인): 사례 정답 기준이 시드와 맞는가 ----------
def _week_of(day: str) -> tuple[date, date]:
    d = date.fromisoformat(day)
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _visible_to(event, user: str) -> bool:
    return event.owner == user or user in event.share_with


def test_case_a_seed_truth_family_todos_are_open_and_the_other_familys_todo_is_isolated():
    family = [t for t in seed.TODOS if t.creator in seed.FAMILY_USERS]
    other = [t for t in seed.TODOS if t.creator == seed.OUTSIDER]
    assert {t.title for t in family} == {
        "우유 사기",
        "학교 준비물 챙기기",
        "보험 서류 제출",
        "도시락 재료 사기",
    }
    assert not hasattr(
        family[0], "done"
    )  # 시드에는 완료한 할 일이 없다: 가족 공동 할 일 4건이 모두 '아직 안 끝난' 것이다
    assert [t.title for t in other] == ["이웃가족 재활용 정리"]
    case = case_files.load_cases(TODO, "dev")[0]
    assert case.id == FAMILY and case.expect.answer.contains == ["우유 사기"]
    assert (
        "이웃가족 재활용 정리" in case.expect.security.forbidden_strings
    )  # 다른 가족 할 일은 답에 나오면 안 된다


def test_case_b_seed_truth_the_week_events_visible_to_the_asker_and_isolation():
    start, end = _week_of(seed.REFERENCE_DAY)
    assert (start.isoformat(), end.isoformat()) == ("2026-11-09", "2026-11-15")
    visible = [
        e
        for e in seed.EVENTS
        if _visible_to(e, "지민") and start <= date.fromisoformat(e.day) <= end
    ]
    assert {e.title for e in visible} == {"치과 진료", "학부모 상담", "가족 외식", "할머니 댁 방문"}
    assert [e.title for e in visible if e.status == "pending"] == ["할머니 댁 방문"]  # 확정 전 후보
    assert not [e for e in seed.EVENTS if e.kind == 2]  # 일정 탭에 '할 일' 종류 일정은 시드에 없다
    # 같은 주가 아니거나 지민에게 보이지 않거나 다른 가족의 일정은 근거가 아니다
    others = {e.title: e for e in seed.EVENTS}
    assert not _visible_to(others["현장체험학습"], "지민")  # 민수의 일정(공유 없음)
    assert date.fromisoformat(others["수진 요가"].day) > end
    assert others["이웃가족 캠핑"].owner == seed.OUTSIDER
    case = case_files.load_cases(TODO, "dev")[1]
    assert case.id == TAB
    any_of = {w for group in case.expect.answer.contains_any for w in group}
    assert any_of <= {
        e.title for e in visible
    }  # 정답 기준의 낱말은 모두 그 주 지민의 확정 일정이다
    assert "이웃가족 캠핑" in case.expect.security.forbidden_strings
