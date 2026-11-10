"""평가 프로세스의 바깥 연결을 소켓 수준에서 막는다(푸시·메일·소셜 로그인·서버 점검 같은 외부 서비스 쓰기 방지).

허용하는 곳은 이 컴퓨터(루프백·유닉스 소켓)와 `allow_hosts` 로 이름을 정해 준 호스트뿐이다. 가짜 모델만 쓰는
시험은 `allow_hosts` 를 비워서 이 컴퓨터 밖으로는 아무것도 나가지 못하게 한다. 이름 조회(getaddrinfo)도 허용 밖이면
DNS 를 부르기 전에 막고, 허용한 호스트가 돌려준 주소만 연결을 허용한다(허용 호스트 이름으로 다른 IP 에 붙는 것은 막지 못하므로
HTTPS 인증서 검사는 그대로 둔다).
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


@contextmanager
def block_network(allow_hosts: Iterable[str] = ()) -> Iterator[None]:
    names = {h.lower() for h in allow_hosts}
    allowed_ips: set[str] = set()
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name is None or name.lower() in LOOPBACK_NAMES or _is_loopback(name):
            return real_getaddrinfo(host, *args, **kwargs)
        if name.lower() not in names:
            raise NetworkBlocked(f"허용하지 않은 호스트 조회: {name}")
        found = real_getaddrinfo(host, *args, **kwargs)
        allowed_ips.update(item[4][0] for item in found)
        return found

    def check(address) -> None:
        if isinstance(address, str | bytes):  # 유닉스 소켓: 이 컴퓨터 안
            return
        host = address[0]
        if not (_is_loopback(host) or host in allowed_ips):
            raise NetworkBlocked(f"허용하지 않은 연결: {host}")

    def guarded_connect(self, address):
        check(address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        check(address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    try:
        yield
    finally:
        socket.getaddrinfo = real_getaddrinfo
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex
