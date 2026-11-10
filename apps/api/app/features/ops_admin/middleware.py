"""요청 계측 미들웨어: trace id 발급(`X-Trace-Id`)과 요청 지표 집계.

`OPS_METRICS_ENABLED` 가 꺼져 있으면(기본) 아무것도 하지 않고 요청을 그대로 넘긴다. 켜져 있어도 계측 중 어떤 오류가 나든
요청 처리에는 영향을 주지 않는다. 경로는 URL 원문이 아니라 라우트 패턴(`/items/{id}`)만 쓴다.
"""

import logging
import time
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.config import settings

from . import service

logger = logging.getLogger(__name__)

TRACE_HEADER = b"x-trace-id"


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not settings.ops_metrics_enabled:
            await self.app(scope, receive, send)
            return

        trace_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["trace_id"] = trace_id
        started = time.perf_counter()
        status = 500  # 응답이 시작되기 전에 예외가 나면 서버 오류로 센다

        async def send_with_trace(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (TRACE_HEADER, trace_id.encode())],
                }
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace)
        finally:
            await self._record(scope, status, (time.perf_counter() - started) * 1000)

    async def _record(self, scope: Scope, status: int, duration_ms: float) -> None:
        try:
            route = service.normalize_route(service.route_template(scope))
            due = service.aggregator.record(scope.get("method", ""), route, status, duration_ms)
            if due:  # 새 구간이 시작됐다: 지난 구간을 저장한다(응답은 이미 나갔다)
                await run_in_threadpool(service.aggregator.flush)
        except Exception as exc:  # 계측 실패가 요청에 영향을 주면 안 된다
            logger.warning("ops metrics record failed: %s", type(exc).__name__)
