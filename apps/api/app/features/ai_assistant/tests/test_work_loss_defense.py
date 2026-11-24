# ruff: noqa: F811
"""응답 뒤 작업(프로세스 안 스레드·메모리 대기열) 유실에 대한 **관측·오류 상태** 방어 시험.

이 시험이 확인하는 것(영속 큐·원본 영속 저장소 없이 가능한 범위만):
- 큐가 가득 차면 사진이 15분 동안 조용히 pending 으로 남지 않고 failed(`QueueFull`)로 적힌다(직접 누른 저장은 버리지 않는다).
- 서버를 끄기 전에 아직 시작하지 않은 작업을 취소하면 사진 판별은 failed(`Shutdown`)로 적혀 업로더가 바로 다시 검사할 수 있고, 자리 표시(대기 수·바이트·진행 집합)가 되돌려진다.
- 기동 때 오래된 `received`·`pending` 이 남아 있으면 건수만 로그로 알리고 아무것도 바꾸지 않는다. DB 가 안 돼도 기동을 막지 않는다.
- 같은 문서 등록이 다시 불려도 한 번만 등록되고 외부 AI 도 다시 부르지 않는다.
이 시험은 **작업 완료를 보장한다고 주장하지 않는다**: 진행 중 작업과 메모리 대기열은 프로세스가 강제 종료되면 사라지고, 원본이 영속 저장소에 없으면 재처리는 복구되지 않는다.
외부 AI 는 대역이다(실제 호출·개인정보 없음, 합성 데이터)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.features.ai_assistant import library, models
from app.features.ai_assistant import repository as ai_repo
from app.features.ai_assistant.tests.test_consent_ingest_flow import (  # noqa: F401  (픽스처·도우미 재사용; 자동 인라인 실행 픽스처는 가져오지 않는다)
    PLAIN_TEXT,
    _chat_file,
    _check,
    _items,
    _send_photo,
    claude,
    family,
)
from app.features.family_chat.models import ChatPhotoCheck
from app.shared.db import SessionLocal

_REAL_SUBMIT = library._submit  # 루트 conftest 가 시험마다 `_submit` 을 아무것도 안 하는 함수로 바꾸므로, 진짜 함수를 가져올 때 붙잡아 둔다


@pytest.fixture(autouse=True)
def _clean_library_state(monkeypatch):
    monkeypatch.setattr(
        library, "_submit", _REAL_SUBMIT
    )  # 이 파일은 실제 대기열·스레드를 시험한다(필요한 시험은 스스로 바꾼다)
    library._photo_pending.clear()
    library._photo_inflight.clear()
    monkeypatch.setattr(library, "_photo_bytes", 0)
    with library._jobs_lock:
        library._jobs.clear()
    yield
    library._photo_pending.clear()
    library._photo_inflight.clear()


def test_cancelling_queued_photo_jobs_marks_them_failed_so_they_can_be_rechecked(
    client, family, monkeypatch, caplog
):
    a, _, _ = family
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(library, "_executor", executor)
    gate, started = threading.Event(), threading.Event()
    library._submit(lambda: (started.set(), gate.wait(10)))  # 처리 칸 하나를 붙잡는 작업
    assert started.wait(5)
    att = _send_photo(client, a)  # 그 뒤에 줄을 선다
    assert library.queue_stats() == {"queued": 1, "running": 1}
    assert _check(att).status == "pending"

    with caplog.at_level(logging.WARNING, logger=library.logger.name):
        result = library.shutdown_report()

    assert result == {"cancelled": 1, "running": 1}  # 진행 중인 작업은 건드리지 않는다
    row = _check(att)
    assert (row.status, row.last_error) == (
        "failed",
        "Shutdown",
    )  # 15분을 기다리지 않고 바로 다시 검사할 수 있다
    assert library._photo_pending == {} and library._photo_inflight == set()
    assert library._photo_bytes == 0  # 대기 자리가 되돌려졌다
    assert "cancelled_queued=1" in caplog.text and "running_may_be_lost=1" in caplog.text
    gate.set()
    executor.shutdown(wait=True)
    assert library.queue_stats() == {"queued": 0, "running": 0}


def test_cancel_does_not_touch_a_job_that_already_started(client, family, monkeypatch):
    a, _, _ = family
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(library, "_executor", executor)
    gate, started = threading.Event(), threading.Event()
    seen = []
    monkeypatch.setattr(
        library,
        "register_chat_photo",
        lambda *args, **kw: (started.set(), gate.wait(10), seen.append(args[2])),
    )
    att = _send_photo(client, a)
    assert started.wait(5)  # 이 사진 판별은 이미 진행 중이다
    assert library.shutdown_report() == {"cancelled": 0, "running": 1}
    assert _check(att).status == "pending"  # 진행 중인 것은 취소·실패 표시하지 않는다
    gate.set()
    executor.shutdown(wait=True)
    assert seen == [att]


def test_a_full_queue_marks_the_photo_failed_instead_of_leaving_it_pending(
    client, family, monkeypatch
):
    a, _, _ = family
    submitted = []
    monkeypatch.setattr(library, "PHOTO_QUEUE_LIMIT", 0)
    monkeypatch.setattr(library, "_submit", lambda fn, *args: submitted.append(fn))
    att = _send_photo(client, a)
    row = _check(att)
    assert (row.status, row.last_error) == ("failed", "QueueFull")
    assert submitted == []  # 큐에 넣지 않았다


def test_a_forced_save_is_never_dropped_by_a_full_queue(client, family, monkeypatch):
    a, _, group = family
    submitted = []
    monkeypatch.setattr(library, "PHOTO_QUEUE_LIMIT", 0)
    monkeypatch.setattr(library, "_submit", lambda fn, *args: submitted.append(fn))
    att = _send_photo(client, a)
    uid = client.get("/family-group/me", headers=a).json()["id"]
    library._on_photo(group["id"], uid, att, b"x", True)  # 사용자가 직접 누른 저장
    assert len(submitted) == 1  # 큐가 가득 차도 버리지 않는다
    assert (
        _check(att).last_error == "QueueFull"
    )  # 위의 자동 판별 한 건만 failed 로 적혔다(직접 저장은 상태를 바꾸지 않는다)


def test_startup_report_counts_stale_work_and_changes_nothing(client, family, monkeypatch, caplog):
    a, _, group = family
    monkeypatch.setattr(
        library, "_submit", lambda fn, *args: None
    )  # 판별이 시작되지 않아 pending 으로 남는다
    att = _send_photo(client, a)
    old = datetime.now(UTC) - timedelta(minutes=30)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck).where(ChatPhotoCheck.attachment_id == att).values(created_at=old)
        )
        db.add(
            models.Photo(
                id="stale-received",
                group_id=group["id"],
                uploaded_by="u",
                filename="a.pdf",
                content_type="application/pdf",
                size=1,
                status="received",
                created_at=old,
            )
        )
        db.add(
            models.Photo(
                id="fresh-received",
                group_id=group["id"],
                uploaded_by="u",
                filename="b.pdf",
                content_type="application/pdf",
                size=1,
                status="received",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    with caplog.at_level(logging.INFO, logger=library.logger.name):
        library.startup_report()

    assert (
        "stale_received=1 stale_pending_photos=1" in caplog.text
    )  # 오래된 것만 센다(방금 받은 것은 아니다)
    with SessionLocal() as db:
        assert db.get(ChatPhotoCheck, att).status == "pending"  # 읽기 전용: 아무것도 바꾸지 않는다
        assert db.get(models.Photo, "stale-received").status == "received"


def test_startup_report_never_blocks_startup_when_the_database_fails(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ai_repo, "count_stale_received", boom)
    with caplog.at_level(logging.WARNING, logger=library.logger.name):
        library.startup_report()  # 던지지 않는다
    assert "startup report failed" in caplog.text


def test_retrying_the_same_document_registration_registers_it_once_and_sends_nothing_more(
    client, family, claude, monkeypatch
):
    a, _, group = family
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    _chat_file(client, a, "a.txt", PLAIN_TEXT.encode(), "text/plain")
    (item,) = _items(group["id"])
    uid = client.get("/family-group/me", headers=a).json()["id"]
    before = dict(claude.calls)
    library.register_chat_document(  # 같은 첨부가 다시 맡겨졌다(재시도·중복 요청)
        group["id"], uid, item.source_attachment_id, "a.txt", "text/plain", PLAIN_TEXT.encode()
    )
    assert len(_items(group["id"])) == 1
    assert claude.calls == before  # 읽기·가리기·분류를 다시 부르지 않았다


def test_the_app_lifespan_runs_the_startup_and_shutdown_reports(monkeypatch):
    """운영 기동·종료 경로가 두 보고 함수를 실제로 부른다(시험 서버의 lifespan 으로 확인)."""
    from fastapi.testclient import TestClient

    from app import main

    calls = []
    monkeypatch.setattr(main.chat_library_work, "startup_report", lambda: calls.append("start"))
    monkeypatch.setattr(main.chat_library_work, "shutdown_report", lambda: calls.append("stop"))
    with TestClient(main.app):
        assert calls == ["start"]
    assert calls == ["start", "stop"]
