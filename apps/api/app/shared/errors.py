from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """에러 응답은 항상 {"code": ..., "message": ...} 형식이다."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def not_found(what: str = "대상") -> ApiError:
    return ApiError(404, "not_found", f"{what}을(를) 찾을 수 없어요")


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(400, code, message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
