"""E4c-2 최소 재현: `eval_hook.recording()`(contextvars)이 ASGI 요청 경계를 넘어 관찰을 남기는가(L0, 가짜 모델·네트워크 없음).

결과(이 환경: starlette `TestClient` + anyio, httpx `ASGITransport`)는 아래 시험이 고정한다.
- (a) `TestClient`(별도 스레드의 anyio 포털에서 앱을 돈다): 호출 쪽에서 연 `recording()` 에 관찰이 **남는다**.
  anyio 가 포털 호출·`to_thread.run_sync` 마다 호출 쪽의 컨텍스트 복사본에서 실행하고, `Recording` 은 복사해도 같은 객체라서다.
- (b) `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`: 같은 이벤트 루프에서 요청해도, 동기 엔드포인트(스레드풀 경유)도 **남는다**.
- 그래서 신규 사례의 입구로 `POST /ai-assistant/chat`(audience·room_id)을 쓸 수 있다.
- 한계: 이 보장은 "같은 컨텍스트 복사본에서 도는 호출"에만 해당한다. 앱이 `contextvars.Context()` 를 새로 만들거나 컨텍스트를
  복사하지 않고 스레드를 직접 띄우면(`threading.Thread(...).start()`) 기록이 사라진다(아래 시험이 고정). 운영 코드의 도구 루프는
  요청을 처리하는 한 스레드에서 차례로 돈다(`eval_hook` 머리말). 백그라운드로 도는 작업의 도구 호출은 기록되지 않는다.
- 안전장치: 기록이 0건이면 실행기는 "관찰 누락"으로 실패 처리한다(`runner.py`).
"""

import asyncio
import contextvars
import threading

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.shared.llm import eval_hook

TOOL_CALL = [{"id": "t1", "name": "list_items", "args": {"limit": 3}}]
TOOL_OUT = [("t1", "{}", False)]


def _observe() -> None:
    eval_hook.observe_tools("main", TOOL_CALL, TOOL_OUT)


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/sync")
    def sync_endpoint() -> dict:  # 스레드풀에서 돈다
        _observe()
        return {"ok": True}

    @app.get("/async")
    async def async_endpoint() -> dict:  # 이벤트 루프에서 바로 돈다
        _observe()
        return {"ok": True}

    @app.get("/raw-thread")
    def raw_thread_endpoint() -> dict:  # 컨텍스트를 복사하지 않는 새 스레드
        t = threading.Thread(target=_observe)
        t.start()
        t.join()
        return {"ok": True}

    @app.get("/copied-thread")
    def copied_thread_endpoint() -> dict:  # 컨텍스트를 복사해 넘긴 스레드
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: ctx.run(_observe))
        t.start()
        t.join()
        return {"ok": True}

    return app


def _names(rec: eval_hook.Recording) -> list[str]:
    return [c["name"] for c in rec.calls]


def test_a_testclient_keeps_the_observation_for_sync_and_async_endpoints():
    with TestClient(_make_app()) as client:
        for path in ("/sync", "/async"):
            with eval_hook.recording() as rec:
                assert client.get(path).status_code == 200
            assert _names(rec) == ["list_items"], path


def test_b_httpx_asgi_transport_keeps_the_observation_in_the_same_event_loop():
    async def go() -> dict[str, list[str]]:
        found = {}
        transport = httpx.ASGITransport(app=_make_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/sync", "/async"):
                with eval_hook.recording() as rec:
                    assert (await client.get(path)).status_code == 200
                found[path] = _names(rec)
        return found

    assert asyncio.run(go()) == {"/sync": ["list_items"], "/async": ["list_items"]}


def test_c_limit_a_thread_started_without_copying_the_context_loses_the_observation():
    """보장의 한계: 컨텍스트를 복사하지 않고 직접 띄운 스레드의 기록은 사라진다(복사해 넘기면 남는다)."""
    with TestClient(_make_app()) as client:
        with eval_hook.recording() as lost:
            client.get("/raw-thread")
        with eval_hook.recording() as kept:
            client.get("/copied-thread")
    assert _names(lost) == []
    assert _names(kept) == ["list_items"]


def test_requests_do_not_share_recordings_between_concurrent_calls():
    """두 `recording()` 이 번갈아 열려도 각 요청의 관찰은 자기 기록에만 남는다."""
    with TestClient(_make_app()) as client:
        with eval_hook.recording() as first:
            client.get("/sync")
            with eval_hook.recording() as inner:
                client.get("/sync")
                client.get("/async")
            client.get("/async")
    assert len(first.calls) == 2 and len(inner.calls) == 2
