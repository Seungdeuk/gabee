"""경로 스위치: 설정 DISABLED_AI_ROUTES 에 걸린 요청을 라우터에 닿기 전에 503 route_disabled 로 돌려준다.

팀원이 AI 비서 코드를 가명화 게이트웨이에 연결하기 전까지의 임시 방어다(docs/security/LLM_EGRESS_TEMP_GUARDS.md).
- 형식: 쉼표로 구분한 `METHOD /path` 목록. 경로의 `*` 는 와일드카드(fnmatch, `/` 도 포함해 맞는다). 메서드는 대소문자 무관.
- 빈 값(기본)이면 아무 것도 끄지 않는다. 잘못된 항목은 무시한다(서버 시작을 막지 않는다).
- 설정은 요청 시점에 읽는다(시험에서 monkeypatch 로 바꿀 수 있다).
- 순수 ASGI 미들웨어다(BaseHTTPMiddleware 를 쓰지 않아 본문 스트림을 건드리지 않는다).
"""

import json
from fnmatch import fnmatchcase

from starlette.types import ASGIApp, Receive, Scope, Send

from app.shared.config import settings

_BODY = json.dumps(
    {"code": "route_disabled", "message": "이 기능은 지금 잠시 꺼져 있어요"}, ensure_ascii=False
).encode()
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def parse_rules(raw: str) -> list[tuple[str, str]]:
    """'POST /a/*, get /b' -> [('POST', '/a/*'), ('GET', '/b')]. 형식이 틀린 항목은 버린다."""
    rules: list[tuple[str, str]] = []
    for item in (raw or "").split(","):
        parts = item.split()
        if len(parts) != 2:
            continue
        method, path = parts[0].upper(), parts[1]
        if method in _METHODS and path.startswith("/"):
            rules.append((method, path))
    return rules


def is_disabled(method: str, path: str, raw: str) -> bool:
    """method/path 가 raw 규칙 중 하나에 걸리는지. 끝의 '/' 하나는 무시한다."""
    method = method.upper()
    path = path.rstrip("/") or "/"
    return any(m == method and fnmatchcase(path, p.rstrip("/") or "/") for m, p in parse_rules(raw))


class RouteSwitchMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raw = settings.disabled_ai_routes
        if scope["type"] == "http" and raw and is_disabled(scope["method"], scope["path"], raw):
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_BODY)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _BODY})
            return
        await self.app(scope, receive, send)
