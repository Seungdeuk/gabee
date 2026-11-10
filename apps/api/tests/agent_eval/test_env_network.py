"""평가 중 바깥 연결 차단 시험(L0). 실제 외부 호스트에는 연결하지 않는다."""

import smtplib
import socket

import httpx
import pytest

from evals.agent_eval.network import NetworkBlocked, block_network


def test_unlisted_hostname_is_blocked_before_dns():
    with block_network(), pytest.raises(NetworkBlocked):
        socket.getaddrinfo("push.example.com", 443)


def test_literal_remote_address_is_blocked():
    with block_network(), pytest.raises(NetworkBlocked):
        socket.socket().connect(("93.184.216.34", 80))
    with block_network(), pytest.raises(NetworkBlocked):
        socket.socket().connect_ex(("93.184.216.34", 80))


def test_loopback_and_unix_style_addresses_still_work():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    with block_network():
        client = socket.create_connection(server.getsockname(), timeout=2)
    client.close()
    server.close()


def test_real_clients_for_push_and_mail_cannot_leave_the_machine():
    with block_network():
        with pytest.raises((NetworkBlocked, httpx.HTTPError)):
            httpx.post("https://exp.host/--/api/v2/push/send", json={}, timeout=2)
        with pytest.raises(NetworkBlocked):
            smtplib.SMTP("smtp.example.com", 25, timeout=2)


def test_only_the_named_host_and_the_addresses_it_resolved_are_allowed(monkeypatch):
    reached = []
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))]
    )
    monkeypatch.setattr(socket.socket, "connect", lambda self, addr: reached.append(addr))
    with block_network(allow_hosts=("llm.test",)):
        socket.getaddrinfo("llm.test", 443)
        socket.socket().connect(("10.1.2.3", 443))  # 허용한 호스트가 돌려준 주소
        with pytest.raises(NetworkBlocked):
            socket.socket().connect(("10.9.9.9", 443))  # 그 밖의 주소
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("other.test", 443)
    assert reached == [("10.1.2.3", 443)]


def test_everything_is_restored_after_the_block_even_on_error():
    before = (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex)
    with pytest.raises(ZeroDivisionError), block_network():
        raise ZeroDivisionError
    assert (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex) == before
