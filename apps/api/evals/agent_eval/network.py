"""평가 프로세스의 바깥 연결을 막는다(푸시·메일·소셜 로그인·서버 점검 같은 외부 서비스 쓰기 방지).

허용하는 곳은 이 컴퓨터(루프백·유닉스 소켓)와 `allow_hosts` 로 이름을 정해 준 호스트뿐이다. 가짜 모델만 쓰는
시험은 `allow_hosts` 를 비워서 이 컴퓨터 밖으로는 아무것도 나가지 못하게 한다.

막는 곳(파이썬 수준): `socket.socket.connect`·`connect_ex`·`sendto`, `socket.getaddrinfo`·`gethostbyname`·`gethostbyname_ex`,
asyncio 이벤트 루프의 `sock_connect`(Windows 기본 루프는 `socket.connect` 를 거치지 않는다). 이름 조회는 허용 밖이면 DNS 를 부르기 전에
막고, 허용한 호스트가 돌려준 주소만 연결을 허용한다.
못 막는 곳: C 확장이 직접 여는 소켓(예: libpq)과 이 프로세스가 아닌 다른 프로세스. DB 는 `env.check_process_boundary` 가 임시 SQLite 만
허용해서 막고, 이 차단은 그 위에 한 겹을 더하는 것이다.
"""

import ipaddress
import socket
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


class NetworkBlocked(RuntimeError):
    """평가 중 허용하지 않은 바깥 연결을 시도했다."""


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _loops() -> list[type]:
    from asyncio import proactor_events, selector_events

    return [selector_events.BaseSelectorEventLoop, proactor_events.BaseProactorEventLoop]


@contextmanager
def block_network(allow_hosts: Iterable[str] = ()) -> Iterator[None]:
    names = {h.lower() for h in allow_hosts}
    allowed_ips: set[str] = set()
    sock_cls = socket.socket
    saved_funcs = {
        n: getattr(socket, n) for n in ("getaddrinfo", "gethostbyname", "gethostbyname_ex")
    }
    saved_methods = {n: getattr(sock_cls, n) for n in ("connect", "connect_ex", "sendto")}
    saved_loops = [(cls, cls.sock_connect) for cls in _loops()]

    def allowed_name(host) -> bool:
        name = host.decode() if isinstance(host, bytes) else host
        return name is None or name.lower() in LOOPBACK_NAMES or _is_loopback(name)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if allowed_name(host):
            return saved_funcs["getaddrinfo"](host, *args, **kwargs)
        name = host.decode() if isinstance(host, bytes) else host
        if name.lower() not in names:
            raise NetworkBlocked(f"허용하지 않은 호스트 조회: {name}")
        found = saved_funcs["getaddrinfo"](host, *args, **kwargs)
        allowed_ips.update(item[4][0] for item in found)
        return found

    def guarded_by_name(real):
        def call(host):
            if not allowed_name(host) and str(host).lower() not in names:
                raise NetworkBlocked(f"허용하지 않은 호스트 조회: {host}")
            return real(host)

        return call

    def check(address) -> None:
        if isinstance(address, str | bytes):  # 유닉스 소켓: 이 컴퓨터 안
            return
        host = address[0]
        if not (_is_loopback(host) or host in allowed_ips):
            raise NetworkBlocked(f"허용하지 않은 연결: {host}")

    def guarded_method(name):
        real = saved_methods[name]

        def call(self, *args):
            check(args[-1])  # connect(addr), sendto(data, addr), sendto(data, flags, addr)
            return real(self, *args)

        return call

    def guarded_sock_connect(real):
        async def call(self, sock, address):
            check(address)
            return await real(self, sock, address)

        return call

    socket.getaddrinfo = guarded_getaddrinfo
    socket.gethostbyname = guarded_by_name(saved_funcs["gethostbyname"])
    socket.gethostbyname_ex = guarded_by_name(saved_funcs["gethostbyname_ex"])
    for name in saved_methods:
        setattr(sock_cls, name, guarded_method(name))
    for cls, real in saved_loops:
        cls.sock_connect = guarded_sock_connect(real)
    try:
        yield
    finally:
        for name, real in saved_funcs.items():
            setattr(socket, name, real)
        for name, real in saved_methods.items():
            setattr(sock_cls, name, real)
        for cls, real in saved_loops:
            cls.sock_connect = real
