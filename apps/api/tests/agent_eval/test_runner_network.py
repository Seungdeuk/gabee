"""가짜 모델 실행 중 네트워크 차단과 실제 호출 0회(L0): 소켓이 막혀 있고, 전송 함수는 가짜만 불린다."""

import socket

import httpx
import pytest

from app.shared.llm import transport
from evals.agent_eval import runner
from evals.agent_eval.network import NetworkBlocked
from tests.agent_eval.runner_support import legacy, new_case, run


@pytest.fixture
def no_real_http(monkeypatch):
    """httpx 로 나가는 모든 길을 막고 부르면 시험을 실패시킨다."""
    sent = []

    def boom(*args, **kwargs):
        sent.append(args)
        raise AssertionError("실제 HTTP 호출을 시도했다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "request", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    return sent


def test_sockets_to_outside_hosts_are_blocked_while_the_fake_run_is_going(
    monkeypatch, no_real_http
):
    probes = []
    real = runner._ask_legacy

    def spy(lc):
        outcome = {}
        # 실제로 닿지 않는 주소(RFC 5737 TEST-NET·.invalid)만 쓴다: 차단이 깨져도 외부로 나가지 않고 OSError 로 끝난다
        s = socket.socket()
        s.settimeout(0.2)
        for label, action in (
            ("lookup", lambda: socket.getaddrinfo("blocked.invalid", 443)),
            ("connect", lambda: s.connect(("192.0.2.1", 443))),
            ("create_connection", lambda: socket.create_connection(("blocked.invalid", 80), 0.2)),
        ):
            try:
                action()
                outcome[label] = "열렸다"
            except NetworkBlocked:
                outcome[label] = "막힘"
            except OSError:
                outcome[label] = "막히지 않음"
        s.close()
        probes.append(outcome)
        return real(lc)

    monkeypatch.setattr(runner, "_ask_legacy", spy)
    report = run(legacy("b-total", "m-billing"))
    assert all(set(p.values()) == {"막힘"} and len(p) == 3 for p in probes) and len(probes) == 2
    assert [r.status for r in report.records] == ["judged", "judged"] and no_real_http == []


def test_the_block_is_lifted_after_the_run_and_the_real_transport_is_untouched(no_real_http):
    real_post = transport.post_messages
    names = ("getaddrinfo", "gethostbyname", "gethostbyname_ex")
    before = {n: getattr(socket, n) for n in names}
    before_methods = {n: getattr(socket.socket, n) for n in ("connect", "connect_ex", "sendto")}
    run(legacy("b-total"))
    assert transport.post_messages is real_post
    assert {
        n: getattr(socket, n) for n in names
    } == before  # 차단은 실행이 끝나면 원래 함수로 돌아간다
    assert {n: getattr(socket.socket, n) for n in before_methods} == before_methods


def test_every_model_call_is_a_fake_call_and_the_counts_agree(no_real_http):
    report = run(legacy("b-total", "m-billing", "b-write-propose"), repeats=2)
    fake_calls = sum(f.calls for f in report.fakes.values())
    assert fake_calls == len(report.ledger.usages) == sum(r.llm_calls for r in report.records) == 14
    assert no_real_http == []  # httpx 는 한 번도 불리지 않았다(실제 호출 0회)
    assert all(u.model == "claude-haiku-5-5" for u in report.ledger.usages)


def test_the_api_key_in_the_settings_is_replaced_by_a_placeholder_during_a_fake_run(
    monkeypatch, no_real_http
):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-real-looking-secret")
    seen = []
    real = runner._ask_legacy

    def spy(lc):
        seen.append(settings.anthropic_api_key)
        return real(lc)

    monkeypatch.setattr(runner, "_ask_legacy", spy)
    run(legacy("b-total"))
    assert seen == [runner.FAKE_KEY]  # 실제 키가 설정돼 있어도 가짜 모드는 쓰지 않는다
    assert settings.anthropic_api_key == "sk-real-looking-secret"  # 끝나면 되돌린다


def test_the_chat_entrance_also_makes_no_real_call(no_real_http):
    from tests.agent_eval.runner_support import ask_billing_script

    case = new_case("n-net")
    report = run([case], scripts={"n-net": ask_billing_script()})
    assert report.records[0].status == "judged" and no_real_http == []
