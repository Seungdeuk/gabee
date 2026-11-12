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


def test_loopback_to_a_service_that_was_already_running_is_blocked_but_one_opened_inside_works():
    """미리 떠 있던 로컬 서비스(프록시 등)는 바깥으로 이어질 수 있어 막고, 차단 중에 이 프로세스가 연 포트만 허용한다."""
    outside = socket.socket()
    outside.bind(("127.0.0.1", 0))
    outside.listen(1)
    with block_network():
        with pytest.raises(NetworkBlocked):
            socket.create_connection(outside.getsockname(), timeout=2)
        inside = socket.socket()
        inside.bind(("127.0.0.1", 0))
        inside.listen(1)
        client = socket.create_connection(inside.getsockname(), timeout=2)
        client.close()
        inside.close()
    outside.close()


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


def test_asyncio_connections_are_blocked_too_even_by_ip_which_skips_name_lookup():
    """Windows 기본 루프(Proactor)는 socket.connect 를 거치지 않고 IP 면 이름 조회도 건너뛴다."""
    import asyncio

    async def go():
        await asyncio.open_connection("10.255.255.1", 9)

    with block_network(), pytest.raises(NetworkBlocked):
        asyncio.run(go())


def test_async_httpx_cannot_reach_a_remote_address_either():
    import asyncio

    async def go():
        async with httpx.AsyncClient(timeout=2) as client:
            await client.get("http://10.255.255.1:9/")

    def causes(exc):  # anyio 는 원인을 예외 그룹으로 감싸서 올린다
        return (
            [leaf for e in getattr(exc, "exceptions", [exc]) for leaf in causes(e)]
            if hasattr(exc, "exceptions")
            else [exc]
        )

    with block_network(), pytest.raises(BaseException) as raised:
        asyncio.run(go())
    assert any(isinstance(e, NetworkBlocked) for e in causes(raised.value))


def test_gethostbyname_and_udp_sendto_are_guarded():
    with block_network():
        with pytest.raises(NetworkBlocked):
            socket.gethostbyname("push.example.com")
        with pytest.raises(NetworkBlocked):
            socket.gethostbyname_ex("push.example.com")
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(NetworkBlocked):
            udp.sendto(b"x", ("10.255.255.1", 9))
        udp.close()
        assert socket.gethostbyname("localhost") in ("127.0.0.1", "::1")
