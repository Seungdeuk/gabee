"""검색 색인 점검(T12 PR-2): 점검 함수, 시작 경고 로그, 운영자 조회 API, 재색인 도구의 --expect-model.

모든 출력·로그·응답에는 개수와 모델 이름만 있고, 문서 내용·제목·가족 그룹 id 는 없다."""

import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.features.ai_assistant.knowledge import embedding, index_health
from app.features.ai_assistant.knowledge import repository as repo
from app.features.ai_assistant.knowledge.tests.test_reindex import (
    GROUP,
    SECRET_TEXT,
    _models,
    _seed,
)
from app.main import app
from app.shared.config import settings
from app.shared.db import SessionLocal

URL = "/ai-assistant/knowledge/index-status"
SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"


@pytest.fixture(autouse=True)
def _restore_embedder():
    yield
    embedding.set_embedder(None)


def _member(client, login_id: str) -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "시험",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(LOGIN, json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


def test_collect_counts_chunks_by_model(client):
    with SessionLocal() as db:
        _seed(db, 2, model="old-model", tag="a")
        _seed(db, 1, model="new-model", tag="b")
        report = index_health.collect(db, "new-model")
    assert report["current_model"] == "new-model"
    assert report["by_model"] == {"old-model": 2, "new-model": 1}
    assert report["stale_chunks"] == 2
    assert report["stale_items"] == 2  # 다른 모델 조각만 있는 기록 둘
    assert report["missing_items"] == 2  # 지금 모델 조각이 하나도 없어 의미 검색에서 빠진 기록


def test_collect_on_empty_index_is_all_zero(client):
    with SessionLocal() as db:
        report = index_health.collect(db, "new-model")
    assert report["by_model"] == {}
    assert report["stale_chunks"] == report["stale_items"] == report["missing_items"] == 0


def test_warnings_flag_stale_chunks_and_missing_model_folder():
    stale = {"current_model": "new", "stale_chunks": 3, "stale_items": 1, "missing_items": 1}
    assert any("다른 조각이 3개" in w for w in index_health.warnings("sqlite", stale))
    clean = {"current_model": "new", "stale_chunks": 0, "stale_items": 0, "missing_items": 0}
    assert index_health.warnings("sqlite", clean) == []
    hashing = {**clean, "current_model": "hashing-512"}
    assert any(
        "모델 폴더를 찾지 못했어요" in w for w in index_health.warnings("postgresql", hashing)
    )
    assert index_health.warnings("sqlite", hashing) == []  # SQLite 는 해시 임베더도 정상이다


def test_startup_logs_a_warning_with_counts_only(client, monkeypatch, caplog):
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "new-model")
    with SessionLocal() as db:
        _seed(db, 2, model="old-model")
    with caplog.at_level(logging.INFO, logger=index_health.logger.name):
        index_health.log_startup()
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warned and "다른 조각이 2개" in warned[0].getMessage()
    assert "new-model" in warned[0].getMessage()
    text = " ".join(r.getMessage() for r in caplog.records)
    with SessionLocal() as db:  # 실제로 저장된 본문·가족 그룹 id·기록 id 가 로그에 없어야 한다
        item_ids = [row.id for row in db.query(repo.KnowledgeItem).all()]
    assert SECRET_TEXT not in text and GROUP not in text
    assert all(i not in text for i in item_ids)


def test_startup_logs_info_when_everything_matches(client, monkeypatch, caplog):
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "new-model")
    with SessionLocal() as db:
        _seed(db, 2, model="new-model")
    with caplog.at_level(logging.INFO, logger=index_health.logger.name):
        index_health.log_startup()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(r.levelno == logging.INFO for r in caplog.records)


def test_startup_check_never_stops_the_server(monkeypatch, caplog):
    class Boom:
        def __enter__(self):
            raise RuntimeError("db down: secret-host")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(index_health, "SessionLocal", lambda: Boom())
    with caplog.at_level(logging.INFO, logger=index_health.logger.name):
        index_health.log_startup()  # 예외를 밖으로 내보내지 않는다
    assert any("점검하지 못했어요" in r.getMessage() for r in caplog.records)
    assert "secret-host" not in " ".join(r.getMessage() for r in caplog.records)


def test_server_startup_runs_the_check(monkeypatch):
    calls = []
    monkeypatch.setattr(index_health, "log_startup", lambda: calls.append(1))
    with TestClient(app):
        pass
    index_health.join_startup_check()
    assert calls == [1]


def test_startup_check_runs_in_background_so_a_locked_table_cannot_stall_the_server(monkeypatch):
    release = threading.Event()
    done = []

    def slow():  # 표 잠금 때문에 질의가 오래 걸리는 상황을 흉내 낸다
        release.wait(5)
        done.append(1)

    monkeypatch.setattr(index_health, "log_startup", slow)
    started = time.monotonic()
    index_health.start_startup_check()
    assert time.monotonic() - started < 1  # 점검이 끝나기를 기다리지 않고 돌아온다
    assert done == []
    release.set()
    index_health.join_startup_check()
    assert done == [1]


def test_status_api_requires_operator(client, monkeypatch):
    assert client.get(URL).status_code == 401
    headers, _ = _member(client, "plain_user")
    monkeypatch.setattr(settings, "admin_user_ids", "")
    r = client.get(URL, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"


def test_status_api_returns_counts_and_warnings_only(client, monkeypatch):
    headers, user_id = _member(client, "ops_tester")
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "new-model")
    with SessionLocal() as db:
        _seed(db, 2, model="old-model")
    r = client.get(URL, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_model"] == "new-model"
    assert body["by_model"] == {"old-model": 2}
    assert body["stale_chunks"] == 2
    assert set(body) == {
        "current_model",
        "by_model",
        "stale_chunks",
        "stale_items",
        "missing_items",
        "warnings",
    }
    assert body["warnings"]


def test_status_api_is_read_only(client, monkeypatch):
    headers, user_id = _member(client, "ops_reader")
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "new-model")
    with SessionLocal() as db:
        _seed(db, 2, model="old-model")
    client.get(URL, headers=headers)
    with SessionLocal() as db:
        assert _models(db) == {"old-model": 2}
        assert repo.count_stale(db, "new-model") == 2


# ---------- scripts.reindex_embeddings --expect-model ----------


def _run(argv):
    from scripts.reindex_embeddings import main

    return main(argv)


def test_expect_model_mismatch_refuses_apply_before_loading_the_model(client, capsys, monkeypatch):
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "onnx-folder-a")

    def forbid():
        raise AssertionError("모델을 불러오면 안 돼요")

    monkeypatch.setattr(embedding, "get_embedder", forbid)
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--apply", "--yes", "--expect-model", "onnx-server-name"]) == 1
    out = capsys.readouterr().out
    assert "onnx-server-name" in out and "onnx-folder-a" in out
    with SessionLocal() as db:
        assert _models(db) == {"old-model": 2}  # 아무것도 바꾸지 않았다


def test_expect_model_match_allows_apply(client, capsys, monkeypatch):
    from app.features.ai_assistant.knowledge.tests.test_reindex import FakeOnnx

    fake = FakeOnnx()
    embedding.set_embedder(fake)
    monkeypatch.setattr(embedding, "expected_model_name", lambda: fake.name)
    with SessionLocal() as db:
        _seed(db, 2)
    assert _run(["--apply", "--yes", "--expect-model", fake.name]) == 0
    with SessionLocal() as db:
        assert _models(db) == {fake.name: 2}


def test_an_empty_expect_model_is_not_treated_as_missing(client, capsys, monkeypatch):
    from app.features.ai_assistant.knowledge.tests.test_reindex import FakeOnnx

    fake = FakeOnnx()
    embedding.set_embedder(fake)  # 검사가 없으면 다시 만들 수 있는 상태
    monkeypatch.setattr(embedding, "expected_model_name", lambda: fake.name)
    with SessionLocal() as db:
        _seed(db, 1)
    assert _run(["--apply", "--yes", "--expect-model", ""]) == 1
    with SessionLocal() as db:
        assert _models(db) == {"old-model": 1}


def test_apply_without_expect_model_says_the_server_name_was_not_checked(
    client, capsys, monkeypatch
):
    from app.features.ai_assistant.knowledge.tests.test_reindex import FakeOnnx

    fake = FakeOnnx()
    embedding.set_embedder(fake)
    with SessionLocal() as db:
        _seed(db, 1)
    assert _run(["--apply", "--yes"]) == 0
    assert "--expect-model" in capsys.readouterr().out


def test_expect_model_mismatch_is_flagged_in_check_without_failing(client, capsys, monkeypatch):
    monkeypatch.setattr(embedding, "expected_model_name", lambda: "onnx-folder-a")
    with SessionLocal() as db:
        _seed(db, 1)
    assert _run(["--check", "--expect-model", "onnx-server-name"]) == 0
    assert "onnx-server-name" in capsys.readouterr().out
