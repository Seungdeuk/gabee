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


def _loopback_listener():
    """루프백에서 연결을 세는 가짜 프록시. 닿으면 accepted 가 늘어난다."""
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.3)
    state = {"accepted": 0, "stop": False}

    def loop():
        while not state["stop"]:
            try:
                conn, _ = server.accept()
            except (TimeoutError, OSError):
                continue
            state["accepted"] += 1
            conn.close()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    def close():
        state["stop"] = True
        thread.join(2)
        server.close()

    return server.getsockname()[1], state, close


def test_a_loopback_proxy_cannot_carry_a_connection_outside_during_the_block(monkeypatch):
    from evals.agent_eval import network

    port, state, close = _loopback_listener()
    try:
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, f"http://127.0.0.1:{port}")
        with network.block_network():
            with pytest.raises(Exception):  # noqa: B017, PT011  어떤 오류든 좋다: 프록시에 닿지 않는 것이 요점이다
                httpx.get("http://proxy-bypass.invalid/", timeout=1)
            assert state["accepted"] == 0  # 루프백 프록시에 연결하지 않았다
    finally:
        close()


def test_proxy_variables_set_during_the_block_do_not_leak_out_and_a_failure_restores_everything(
    monkeypatch,
):
    import os

    from evals.agent_eval import network

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    with network.block_network():
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:10"  # 차단 중에 생긴 값
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:9" and "HTTPS_PROXY" not in os.environ

    import httpx._utils as httpx_utils

    monkeypatch.delattr(httpx_utils, "getproxies")  # httpx 내부 이름이 사라진 경우
    with pytest.raises(AttributeError), network.block_network():
        pass
    assert (
        os.environ["HTTP_PROXY"] == "http://127.0.0.1:9"
    )  # 환경변수를 먼저 지우지 않으므로 그대로다


def test_proxy_settings_come_back_after_the_block(monkeypatch):
    import os
    import urllib.request

    import httpx._utils as httpx_utils

    from evals.agent_eval import network

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    before = (urllib.request.getproxies, httpx_utils.getproxies)
    with network.block_network():
        assert "HTTPS_PROXY" not in os.environ and urllib.request.getproxies() == {}
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:9"
    assert (urllib.request.getproxies, httpx_utils.getproxies) == before


def test_a_client_built_before_the_block_still_cannot_reach_a_loopback_proxy(monkeypatch):
    """진입 전 환경 프록시로 만든 클라이언트는 프록시 설정을 이미 쥐고 있다. 루프백 연결 자체를 막아 둔다."""
    from evals.agent_eval import network

    port, state, close = _loopback_listener()
    try:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{port}")
        client = httpx.Client(timeout=1)  # 차단 전에 만든다(프록시 설정을 가져간다)
        with network.block_network():
            with pytest.raises(Exception):  # noqa: B017, PT011
                client.get("http://prebuilt-client.invalid/")
            assert state["accepted"] == 0
        client.close()
    finally:
        close()


def test_loopback_sockets_the_process_opens_itself_still_work_during_the_block():
    """asyncio 의 socketpair 처럼 차단 중에 이 프로세스가 bind 한 루프백 포트는 연결된다."""
    import asyncio

    from evals.agent_eval import network

    async def go():
        return await asyncio.sleep(0, "ok")

    with network.block_network():
        assert asyncio.run(go()) == "ok"
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), 1)
        client.close()
        server.close()


def test_the_block_cannot_be_opened_twice_at_once_and_everything_is_restored():
    import urllib.request

    from evals.agent_eval import network

    before = (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.bind,
        urllib.request.getproxies,
    )
    with network.block_network():
        with pytest.raises(RuntimeError, match="겹쳐"):
            with network.block_network():
                pass
        assert socket.getaddrinfo is not before[0]  # 바깥 구간은 그대로 켜져 있다
    assert (
        socket.getaddrinfo,
        socket.socket.connect,
        socket.socket.bind,
        urllib.request.getproxies,
    ) == before
    with network.block_network():  # 거부된 뒤에도 다시 열 수 있다
        pass
