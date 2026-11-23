"""실제 호출 활성화 구조(L0, 실제 호출 0회): 기본 차단, 허가 조건, 직접 실행 경로 보호, 허가의 수명·1회용.

전송 함수는 가짜로 바꾼 상태에서만 실제 경로를 연다. 실제 전송 함수(`transport.post_messages` 원본)·httpx 가 불리면 즉시 실패한다.
"""

import threading
from decimal import Decimal as D
from pathlib import Path

import httpx
import pytest

from app.shared.llm import transport
from evals.agent_eval import fake_model, network, real_gate
from evals.agent_eval.cost import Ledger, Scope
from evals.agent_eval.real_gate import RealGateRefused, real_grant, real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions, default_ledger, run_cases
from tests.agent_eval.runner_support import (
    ask_billing_script,
    legacy,
    new_case,
    real_grant_for,
)

ENV_OK = {real_gate.ENV_NAME: "1"}


def preflight_for(run_id="r", approve="1", split="legacy", ids=("b-total",)):
    return real_gate._mint_preflight(run_id, D(approve), split, frozenset(ids), D("0.01"), "h", 1)


def grant_for(run_id="r", approve="1", split="legacy", ids=("b-total",), **over):
    args = dict(
        approve_usd=approve,
        split=split,
        case_ids=list(ids),
        known_ids=["b-total", "m-billing", "x"],
        run_id=run_id,
        content_hash="h",
        environ=ENV_OK,
    )
    if "preflight" not in over:
        args["preflight"] = preflight_for(run_id, approve, split, ids)
    args.update(over)
    return real_gate.issue_grant(**args)


@pytest.fixture
def no_real_http(monkeypatch):
    """실제 전송 함수와 httpx 로 나가는 모든 길이 불리면 시험을 실패시킨다(가짜 전송 함수는 따로 끼운다)."""
    sent = []

    def boom(*a, **k):
        sent.append(1)
        raise AssertionError("실제 호출을 시도했다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "request", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    return sent


# ---------- 기본 차단과 허가 발급 ----------
def test_the_default_is_blocked_and_no_module_flag_can_open_it():
    assert real_grant() is None
    assert not hasattr(real_gate, "REAL_ENABLED")
    with pytest.raises(ImportError):
        from evals.agent_eval import switches  # noqa: F401  상수 스위치는 없어졌다


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", "1 ", " 1", "2"])
def test_the_environment_variable_must_be_exactly_one(value):
    environ = {} if value is None else {real_gate.ENV_NAME: value}
    with pytest.raises(RealGateRefused, match=real_gate.ENV_NAME):
        grant_for(environ=environ)


@pytest.mark.parametrize(
    "approve", [None, "", "0", "-1", "nan", "inf", "-inf", "abc", True, 0, D("0")]
)
def test_the_approved_amount_must_be_a_positive_finite_number(approve):
    with pytest.raises(RealGateRefused, match="승인 금액"):
        grant_for(approve=approve, preflight=preflight_for())


@pytest.mark.parametrize("split", ["val", "test", "all", "", "other"])
def test_only_legacy_and_dev_may_be_called_for_real(split):
    with pytest.raises(RealGateRefused, match="분할"):
        grant_for(split=split, preflight=preflight_for(split=split))


def test_an_explicit_nonempty_known_unique_case_list_of_at_most_ten_is_required():
    with pytest.raises(RealGateRefused, match="--case"):
        grant_for(ids=(), preflight=preflight_for(ids=()))
    with pytest.raises(RealGateRefused, match="존재하지 않는"):
        grant_for(ids=("b-total", "nope"), preflight=preflight_for(ids=("b-total", "nope")))
    with pytest.raises(RealGateRefused, match="겹친다"):
        grant_for(case_ids=["b-total", "b-total"])
    many = [f"c{i}" for i in range(real_gate.MAX_REAL_CASES + 1)]
    with pytest.raises(RealGateRefused, match="이하"):
        grant_for(ids=many, known_ids=many, preflight=preflight_for(ids=many), case_ids=many)
    ten = many[:-1]
    assert grant_for(
        ids=ten, known_ids=ten, case_ids=ten, preflight=preflight_for(ids=ten)
    ).case_ids == frozenset(ten)


def test_a_passed_preflight_for_the_same_run_is_required():
    with pytest.raises(RealGateRefused, match="사전 점검"):
        grant_for(preflight=None)
    for wrong in (
        preflight_for(run_id="other"),
        preflight_for(approve="2"),
        preflight_for(split="dev"),
        preflight_for(ids=("m-billing",)),
    ):
        with pytest.raises(RealGateRefused, match="다르다"):
            grant_for(preflight=wrong)


def test_refusals_never_contain_the_environment_value_or_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-canary-key-value-0001")
    with pytest.raises(RealGateRefused) as e:
        grant_for(environ={real_gate.ENV_NAME: "sk-canary-key-value-0001"})
    assert "sk-canary" not in str(e.value)


# ---------- 허가의 수명 ----------
def test_the_grant_is_active_only_inside_the_scope_and_released_after_normal_exit():
    grant = grant_for()
    assert real_grant() is None
    with real_grant_scope(grant) as active:
        assert real_grant() is grant and active is grant
    assert real_grant() is None


def test_the_grant_is_released_after_an_exception_and_after_a_keyboard_interrupt():
    grant = grant_for()
    with pytest.raises(ZeroDivisionError), real_grant_scope(grant):
        1 / 0  # noqa: B018
    assert real_grant() is None
    with pytest.raises(KeyboardInterrupt), real_grant_scope(grant):
        raise KeyboardInterrupt
    assert real_grant() is None


def test_opening_a_second_scope_inside_is_refused_and_the_first_stays_until_it_exits():
    first, second = grant_for(), grant_for(run_id="r2", preflight=preflight_for("r2"))
    with real_grant_scope(first):
        with pytest.raises(RealGateRefused, match="겹쳐"):
            with real_grant_scope(second):
                pass
        assert real_grant() is first
    assert real_grant() is None


def test_another_thread_does_not_see_the_grant():
    seen = []
    with real_grant_scope(grant_for()):
        t = threading.Thread(target=lambda: seen.append(real_grant()))
        t.start()
        t.join()
    assert seen == [None]  # 허가를 연 컨텍스트에서만 보인다(안 보이는 쪽이 안전한 쪽)


def test_a_grant_can_be_consumed_only_once():
    grant = grant_for()
    assert not grant.consumed
    grant.consume()
    assert grant.consumed
    with pytest.raises(RealGateRefused, match="이미 한 번"):
        grant.consume()


# ---------- 네트워크 호스트 ----------
def test_the_allowed_host_list_has_exactly_one_entry():
    assert real_gate.REAL_HOSTS == ("api.anthropic.com",)


def test_the_network_guard_opens_the_real_host_only_while_a_grant_is_active():
    with pytest.raises(RealGateRefused):
        with network.block_network(real_gate.REAL_HOSTS):
            pass
    with pytest.raises(RealGateRefused):
        with network.block_network(["API.Anthropic.com"]):
            pass
    with real_grant_scope(grant_for()), network.block_network(real_gate.REAL_HOSTS):
        pass
    with network.block_network(("llm.test",)):  # 다른 호스트 이름(시험용)은 이 규칙과 무관하다
        pass
    with network.block_network():  # 기본은 아무것도 열지 않는다
        with pytest.raises(network.NetworkBlocked):
            import socket

            socket.getaddrinfo("api.anthropic.com", 443)


# ---------- 직접 실행 경로 보호(run_cases) ----------
@pytest.fixture
def key(monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-run-key-0002")


def real_options(run_id="r", approve="1", **kw):
    return RunOptions(run_id, mode="real", approved_usd=D(approve), **kw)


def real_ledger(approve="1"):
    return default_ledger("real", D(approve))


def test_run_cases_in_real_mode_without_a_grant_is_refused_even_with_every_option(
    key, no_real_http
):
    with pytest.raises(RunnerRefused, match="꺼져 있다"):
        run_cases(legacy("b-total"), real_options(), ledger=real_ledger())
    assert no_real_http == []


def test_the_grant_must_match_amount_run_id_cases_split_and_results_folder(
    key, no_real_http, tmp_path
):
    cases = legacy("b-total")
    grant = real_grant_for(cases, results_root=tmp_path / "out")
    untouched = real_ledger()
    with real_grant_scope(grant):
        for options, ledger, text in (
            (real_options(approve="0.5"), real_ledger("0.5"), "승인 금액"),
            (real_options(run_id="zzz"), real_ledger(), "실행 id"),
            (real_options(results_root=tmp_path / "elsewhere"), real_ledger(), "결과 폴더"),
            (real_options(results_root=None), real_ledger(), "결과 폴더"),
        ):
            with pytest.raises(RunnerRefused, match=text):
                run_cases(cases, options, ledger=ledger)
        with pytest.raises(RunnerRefused, match="사례"):
            run_cases(
                [new_case("d-1", split="dev")],
                real_options(results_root=tmp_path / "out"),
                ledger=untouched,
            )
        with pytest.raises(RunnerRefused, match="분할"):
            run_cases(
                [new_case("b-total", split="val")],
                real_options(results_root=tmp_path / "out", purpose="baseline"),
                ledger=untouched,
            )
    # 거부된 시도는 허가를 소진하지 않고 비용도 쓰지 않았다
    assert not grant.consumed and untouched.usages == [] and no_real_http == []


def test_a_matching_grant_runs_through_the_fake_transport_then_is_spent_and_released(
    key, no_real_http, monkeypatch, tmp_path
):
    grant = real_grant_for(legacy("b-total"))
    fake = fake_model.FakeModel(fake_model.script_for(legacy("b-total")[0]))
    with real_grant_scope(grant):
        monkeypatch.setattr(transport, "post_messages", fake)  # 가짜 전송 함수(실제 아님)
        report = run_cases(legacy("b-total"), real_options(), ledger=real_ledger())
        assert report.records[0].status == "judged" and fake.calls == 2
        assert grant.consumed
        # 같은 허가로 두 번째 실행은 거부(승인은 이 실행 한 번에만 유효)
        with pytest.raises(RunnerRefused, match="소진|이미 한 번"):
            run_cases(legacy("b-total"), real_options(), ledger=real_ledger())
        assert fake.calls == 2
    assert real_grant() is None and no_real_http == []


def test_a_real_run_that_raises_still_releases_the_grant(key, no_real_http, monkeypatch):
    grant = real_grant_for(legacy("b-total"))
    monkeypatch.setattr(
        transport, "post_messages", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with pytest.raises(KeyboardInterrupt), real_grant_scope(grant):
        run_cases(legacy("b-total"), real_options(), ledger=real_ledger())
    assert real_grant() is None and grant.spent  # 예외로 끝나도 소진된다


def test_the_session_itself_refuses_real_mode_without_a_grant(key, no_real_http):
    from evals.agent_eval import runner

    with pytest.raises(RunnerRefused, match="꺼져 있다"):
        with runner._session(real_options()):
            pytest.fail("세션이 열리면 안 된다")


def test_the_fake_mode_never_needs_or_opens_a_grant(no_real_http, monkeypatch):
    case = new_case("n-1")
    report = run_cases(
        [case],
        RunOptions("r"),
        scripts={"n-1": ask_billing_script()},
        ledger=Ledger((Scope.RUN,)),
    )
    assert report.records[0].status == "judged" and real_grant() is None
    assert no_real_http == []


def test_there_is_no_module_level_switch_left_in_the_runner():
    from evals.agent_eval import runner

    assert not hasattr(runner, "switches") and runner.REAL_HOSTS == real_gate.REAL_HOSTS
    assert isinstance(Path(real_gate.__file__), Path)
