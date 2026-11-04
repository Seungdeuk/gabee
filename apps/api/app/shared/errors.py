from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask


class ApiError(Exception):
    """에러 응답은 항상 {"code": ..., "message": ...} 형식이다."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.headers = headers


def not_found(what: str = "대상") -> ApiError:
    return ApiError(404, "not_found", f"{what}을(를) 찾을 수 없어요")


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(400, code, message)


# 오류 관찰자: (요청, 상태코드, 오류 code, 메시지, 처리되지 않은 예외 또는 None). 기능 코드를 import 하지 않으려고
# shared 는 함수 자리만 두고 main.py 가 운영 관리자 기록 함수를 연결한다. 관찰자는 응답을 보낸 뒤 백그라운드에서 불리며,
# 어떤 예외가 나도 응답에는 영향이 없다.
ErrorObserver = Callable[[Request, int, str, str, BaseException | None], None]
_observer: ErrorObserver | None = None
OBSERVED_STATUSES = frozenset({401, 403})  # 5xx 에 더해 관찰자에게 알리는 상태코드


def set_error_observer(observer: ErrorObserver | None) -> None:
    global _observer
    _observer = observer


def _observed(
    request: Request, status: int, code: str, message: str, exc: BaseException | None
) -> BackgroundTask | None:
    if _observer is None or not (status >= 500 or status in OBSERVED_STATUSES):
        return None
    return BackgroundTask(_notify, _observer, request, status, code, message, exc)


def _notify(
    observer: ErrorObserver,
    request: Request,
    status: int,
    code: str,
    message: str,
    exc: BaseException | None,
) -> None:
    try:
        observer(request, status, code, message, exc)
    except Exception:  # 관찰 실패가 응답이나 서버에 영향을 주면 안 된다
        pass


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError) -> JSONResponse:
        return JSONResponse(
            {"code": e.code, "message": e.message},
            status_code=e.status,
            headers=e.headers,
            background=_observed(request, e.status, e.code, e.message, None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, e: Exception) -> JSONResponse:
        # 처리되지 않은 예외도 앱 공통 형식으로 돌려준다. 예외 내용은 응답에 담지 않는다.
        # 이 응답은 계측 미들웨어 바깥에서 만들어져 X-Trace-Id 가 자동으로 붙지 않으므로 여기서 붙인다(계측이 켜졌을 때만 있다)
        state = request.scope.get("state")
        trace_id = state.get("trace_id") if isinstance(state, dict) else None
        return JSONResponse(
            {"code": "internal_error", "message": "서버에 문제가 생겼어요"},
            status_code=500,
            headers={"X-Trace-Id": trace_id} if trace_id else None,
            background=_observed(request, 500, "internal_error", str(e), e),
        )
