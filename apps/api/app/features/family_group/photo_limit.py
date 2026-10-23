"""프로필 사진 업로드 경로의 본문 크기 제한(순수 ASGI 미들웨어).

multipart 는 인증·검증보다 먼저 전부 파싱되어 임시 파일로 쌓이므로, 파싱 전에 크기로 거절한다.
Content-Length 가 한도를 넘으면 본문을 읽지 않고 413 을 돌려주고, Content-Length 가 없는(chunked) 요청은 읽은 바이트를 세어
한도를 넘는 순간 중단한다. 해당 경로(POST …/family-group/me/photo)에만 적용된다.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 2 * 1024 * 1024 + 100 * 1024  # 사진 2MB + multipart 여유 약 100KB
PHOTO_PATH_SUFFIX = "/family-group/me/photo"


class _TooLarge(Exception):
    pass


async def _reject(send: Send) -> None:
    body = json.dumps(
        {"code": "photo_too_large", "message": "사진은 2MB 이하만 올릴 수 있어요"},
        ensure_ascii=False,
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class PhotoBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].rstrip("/").endswith(PHOTO_PATH_SUFFIX)
        ):
            await self.app(scope, receive, send)
            return
        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await _reject(send)
                    return
        received = 0
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True  # 파서가 예외를 400 으로 바꿔도 끝에서 413 으로 덮어쓴다
                    raise _TooLarge
            return message

        async def guarded_send(message: Message) -> None:
            if not exceeded:  # 한도를 넘은 뒤 앱이 보내는 응답(400 등)은 버린다
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _TooLarge:
            pass
        if exceeded:
            await _reject(send)
