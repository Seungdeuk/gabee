"""평가 프로세스의 바깥 연결을 막는다(푸시·메일·소셜 로그인·서버 점검 같은 외부 서비스 쓰기 방지).

허용하는 곳은 이 컴퓨터(루프백·유닉스 소켓)와 `allow_hosts` 로 이름을 정해 준 호스트뿐이다. 가짜 모델만 쓰는
시험은 `allow_hosts` 를 비워서 이 컴퓨터 밖으로는 아무것도 나가지 못하게 한다. 실제 모델 호스트(`real_gate.REAL_HOSTS`)는
활성 허가가 있을 때만 허용할 수 있고, 없으면 `RealGateRefused` 다.

막는 곳(파이썬 수준): `socket.socket.connect`·`connect_ex`·`sendto`, `socket.getaddrinfo`·`gethostbyname`·`gethostbyname_ex`,
asyncio 이벤트 루프의 `sock_connect`(Windows 기본 루프는 `socket.connect` 를 거치지 않는다). 이름 조회는 허용 밖이면 DNS 를 부르기 전에
막고, 허용한 호스트가 돌려준 주소만 연결을 허용한다.
프록시: 루프백 프록시(`HTTP_PROXY=http://127.0.0.1:포트`)를 거치면 루프백 허용만으로 바깥에 닿을 수 있어서, 차단 중에는 프록시 환경변수를 비우고 `urllib.request.getproxies`·
`httpx._utils.getproxies`(Windows 레지스트리 프록시 포함)가 빈 값을 돌려주게 한다. 끝나면 되돌린다.
루프백은 차단 중에 이 프로세스가 bind 한 포트(asyncio 의 socketpair 등)로만 연결을 허용한다(미리 떠 있는 로컬 프록시·서비스로 가는 연결은 막는다).
차단 구간은 전역 함수를 바꾸므로 한 번에 하나만 열 수 있고, 겹쳐 열면 `RuntimeError` 다.
못 막는 곳: C 확장이 직접 여는 소켓(예: libpq)과 이 프로세스가 아닌 다른 프로세스. DB 는 `env.check_process_boundary` 가 임시 SQLite 만
허용해서 막고, 이 차단은 그 위에 한 겹을 더하는 것이다.
"""

import ipaddress
import os
import socket
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from . import real_gate

LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
PROXY_ENV = tuple(
    f"{n}{suffix}"
    for n in ("http", "https", "all", "ftp", "no", "ws", "wss")
    for suffix in ("_proxy", "_PROXY")
)


_GUARD = (
    threading.Lock()
)  # 전역 함수를 바꾸므로 차단 구간은 한 번에 하나만 연다(겹치면 복원이 뒤섞인다)


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
def _no_proxies() -> Iterator[None]:
    """프록시 설정이 이 프로세스의 바깥 연결을 우회하지 못하게 한다(환경변수와, `urllib.request`·`httpx._utils` 가 읽는 시스템 설정[Windows 레지스트리 포함]을 비운 것처럼)."""
    import urllib.request

    import httpx._utils as httpx_utils

    saved_urllib = urllib.request.getproxies  # 먼저 읽는다: 없으면 아무것도 바꾸기 전에 멈춘다
    saved_httpx = httpx_utils.getproxies
    saved_env: dict[str, str] = {}
    try:
        saved_env.update({n: os.environ.pop(n) for n in PROXY_ENV if n in os.environ})
        urllib.request.getproxies = lambda: {}
        httpx_utils.getproxies = lambda: {}
        yield
    finally:
        urllib.request.getproxies = saved_urllib
        httpx_utils.getproxies = saved_httpx
        for n in PROXY_ENV:  # 차단 중에 새로 생긴 값도 지우고, 원래 값만 되돌린다
            os.environ.pop(n, None)
        os.environ.update(saved_env)


@contextmanager
def block_network(allow_hosts: Iterable[str] = ()) -> Iterator[None]:
    allow_hosts = tuple(allow_hosts)
    if any(h.lower() in real_gate.REAL_HOSTS for h in allow_hosts):
        real_gate.require_active()  # 실제 모델 호스트는 활성 허가가 있을 때만 연다(없으면 RealGateRefused)
    if not _GUARD.acquire(blocking=False):
        raise RuntimeError("이미 네트워크 차단 구간이 열려 있다(겹쳐 열지 않는다)")
    try:
        with _block(allow_hosts):
            yield
    finally:
        _GUARD.release()


@contextmanager
def _block(allow_hosts: Iterable[str]) -> Iterator[None]:
    names = {h.lower() for h in allow_hosts}
    allowed_ips: set[str] = set()
    own_ports: set[int] = set()  # 차단 중에 이 프로세스가 bind 한 포트(예: asyncio 의 socketpair)
    sock_cls = socket.socket
    saved_funcs = {
        n: getattr(socket, n) for n in ("getaddrinfo", "gethostbyname", "gethostbyname_ex")
    }
    saved_methods = {n: getattr(sock_cls, n) for n in ("connect", "connect_ex", "sendto")}
    saved_bind = sock_cls.bind
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
        if _is_loopback(host):
            # 임의의 루프백 포트(로컬 프록시 등)는 바깥으로 이어질 수 있어 이 프로세스가 연 포트만 허용한다
            if len(address) > 1 and address[1] not in own_ports:
                raise NetworkBlocked(f"허용하지 않은 루프백 연결: {host}:{address[1]}")
            return
        if host not in allowed_ips:
            raise NetworkBlocked(f"허용하지 않은 연결: {host}")

    def guarded_bind(self, address):
        result = saved_bind(self, address)
        if not isinstance(address, str | bytes):
            own_ports.add(self.getsockname()[1])
        return result

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

    with _no_proxies():
        try:
            socket.getaddrinfo = guarded_getaddrinfo
            socket.gethostbyname = guarded_by_name(saved_funcs["gethostbyname"])
            socket.gethostbyname_ex = guarded_by_name(saved_funcs["gethostbyname_ex"])
            for name in saved_methods:
                setattr(sock_cls, name, guarded_method(name))
            sock_cls.bind = guarded_bind
            for cls, real in saved_loops:
                cls.sock_connect = guarded_sock_connect(real)
            yield
        finally:
            _restore(saved_funcs, saved_methods, saved_bind, saved_loops)


def _restore(saved_funcs, saved_methods, saved_bind, saved_loops) -> None:
    sock_cls = socket.socket
    sock_cls.bind = saved_bind
    for name, real in saved_funcs.items():
        setattr(socket, name, real)
    for name, real in saved_methods.items():
        setattr(sock_cls, name, real)
    for cls, real in saved_loops:
        cls.sock_connect = real
