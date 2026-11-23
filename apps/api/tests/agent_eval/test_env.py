"""L2 실행 환경 시험(L0). 임시 SQLite 만 쓰고 가짜 모델도 부르지 않는다(DB·캐시·기억·일정 초안 초기화, 경계, 설정 복원)."""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from evals.agent_eval import env
from evals.agent_eval.env import UnsafeEnvironment, check_database_url
from evals.agent_eval.network import NetworkBlocked


@pytest.fixture
def root() -> Path:
    from app.shared.config import settings

    return Path(settings.data_dir)  # conftest 가 만든 임시 폴더(DB 파일도 이 안에 있다)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://gabee_app@192.168.0.44:5432/gabee",  # 팀 공용 DB
        "postgresql://u@localhost/family-secretary",  # 기존 MVP DB
        "mysql://u@localhost/x",
        "sqlite:///:memory:",
        "sqlite://",
        "sqlite:///other/dir/x.db",
        "sqlite:///file.db?mode=ro&uri=true",
        "not a url",
    ],
)
def test_databases_other_than_a_temp_sqlite_file_are_refused(url, root):
    with pytest.raises(UnsafeEnvironment):
        check_database_url(url, root)


def test_a_path_that_escapes_the_root_is_refused_and_a_file_inside_is_accepted(root):
    check_database_url(f"sqlite:///{root / 'eval.db'}", root)
    with pytest.raises(UnsafeEnvironment):
        check_database_url(f"sqlite:///{root / '..' / 'outside.db'}", root)


def test_the_process_boundary_checks_settings_engine_env_and_data_dir(root, tmp_path, monkeypatch):
    from app.shared.config import settings

    env.check_process_boundary(root)  # 시험 환경은 임시 SQLite 라 통과한다
    with pytest.raises(UnsafeEnvironment):  # 다른 폴더를 허용 폴더로 주면 DB·데이터 폴더가 밖이다
        env.check_process_boundary(tmp_path)
    monkeypatch.setattr(settings, "database_url", "postgresql://u@192.168.0.44/gabee")
    with pytest.raises(UnsafeEnvironment):
        env.check_process_boundary(root)
    monkeypatch.undo()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@192.168.0.44/gabee")
    with pytest.raises(UnsafeEnvironment):
        env.check_process_boundary(root)
    monkeypatch.undo()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    with pytest.raises(UnsafeEnvironment):
        env.check_process_boundary(root)


def test_reset_clears_database_cache_memory_events_and_in_memory_drafts(client, family, root):
    from app.features.ai_assistant import memories
    from app.features.family_group.models import User
    from app.features.schedule.agent import ask
    from app.features.schedule.agent.schemas import Draft
    from app.shared import ai_usage
    from app.shared.db import SessionLocal, engine

    a, _, group = family
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (
        client.post(
            "/schedule/events", json={"title": "치과", "starts_at": when}, headers=a
        ).status_code
        < 300
    )
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.name == "지민")).first()
        memories.remember(db, group["id"], me.id, "좋아하는 팀: T1")
        db.add(
            ai_usage.AiResultCache(
                group_id=group["id"],
                feature="chat_analysis",
                cache_key="k",
                result="{}",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.commit()
    ask._keep_draft(group["id"], me.id, type("R", (), {"draft": Draft(title="치과")})())
    upload = Path(root) / "chat_files" / "a.bin"
    upload.parent.mkdir(exist_ok=True)
    upload.write_bytes(b"x")
    before = env.count_rows(engine)
    assert all(
        before[t] > 0
        for t in ("users", "groups", "events", "assistant_memories", "ai_result_cache")
    )
    assert ask._pending

    env.reset_case_state(root)
    assert not upload.exists()  # 업로드 파일도 비워졌다

    assert env.count_rows(engine) == dict.fromkeys(before, 0)  # 모든 테이블이 비었다
    assert ask._take_draft(group["id"], me.id) is None and not ask._pending
    from tests.helpers import signup

    assert signup(client, "새사람")  # 다시 만든 테이블에서 새 사례를 시작할 수 있다


def test_reset_refuses_an_engine_pointing_outside_the_root(root, tmp_path):
    from sqlalchemy import create_engine

    outside = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    with pytest.raises(UnsafeEnvironment):
        env.reset_case_state(root, outside)
    outside.dispose()


def test_every_module_level_memory_store_in_the_app_is_either_reset_or_known_config():
    """새 모듈 수준 가변 상태(캐시·초안 저장소)나 속도 제한기가 생기면 초기화에서 빠지므로 여기서 알려 준다."""
    import app.main  # noqa: F401  모든 기능 모듈을 불러온다
    from app.shared.rate_limit import FailureLimiter

    config_only = {  # 시작할 때 채워지고 평가 중 바뀌지 않는 등록부·설정
        "app.main.origins",
        "app.main.deps",
        "app.shared.chat_share._providers",
        "app.shared.ai_guard._on_disabled",  # AI 끄기 때 정리 콜백(시작할 때 등록하는 목록)
        "app.shared.member_exit._handlers",  # 가족 나갈 때 정리 콜백(시작할 때 등록하는 목록)
        "app.shared.memory_hooks._attachment_removed",  # AI 추억 동의·삭제 콜백(시작할 때 등록하는 목록)
        "app.shared.memory_hooks._member_withdrawn",
        "app.shared.memory_hooks._family_disabled",
        "app.shared.memory_hooks._photo_excluded",
        "app.features.family_memory.worker._handlers",  # AI 추억 작업 처리 함수(종류별, 시작할 때 등록하는 목록)
        "app.shared.weekly_sources._providers",  # 주간 뉴스 재료 수집 통로(시작할 때 등록하는 목록)
        "app.shared.privacy.ner._warned",  # 경고를 한 번만 내는 표시
        "app.shared.privacy.ner._cache",  # 같은 글에 같은 탐지 결과를 돌려주는 순수 함수 캐시
    }
    found, limiters = set(), set()
    for name, module in list(sys.modules.items()):
        if not name.startswith("app.") or ".tests" in name or module is None:
            continue
        for key, value in vars(module).items():
            if key.startswith("__") or key.isupper() or (key.startswith("_") and key[1:].isupper()):
                continue
            if isinstance(value, FailureLimiter):
                limiters.add(f"{name}.{key}")
            elif isinstance(value, dict | list | set):
                found.add(f"{name}.{key}")
    reset = {f"{m}.{a}" for m, a in env.MEMORY_RESETS}
    assert found - config_only == reset  # 비우지 않는 상태가 없고, 비울 것이 사라지지도 않았다
    assert len(limiters) >= 11 and {
        id(x) for x in env._limiters()
    }  # 제한기는 앱 전체를 훑어 모두 비운다


def test_all_rate_limiters_and_memory_stores_are_emptied_by_reset(root):
    from app.features.ai_assistant import library
    from app.features.family_chat import pin_service
    from app.features.family_group.service import login_limiter
    from app.shared import chat_share

    for limiter in (login_limiter, pin_service.limiter, chat_share.limiter):
        for _ in range(3):
            limiter.record("k")
        assert limiter.retry_after("k", 1, 60) > 0
    library._photo_pending["x"] = 1
    library._photo_inflight.add("y")
    from app.features.schedule.agent import choice

    choice._pending[("g", "u")] = (
        0.0,
        None,
    )  # 같은 이름 일정을 되물은 상태가 다음 사례로 새지 않아야 한다
    env.reset_memory_state()
    for limiter in (login_limiter, pin_service.limiter, chat_share.limiter):
        assert limiter.retry_after("k", 1, 60) == 0
    assert not library._photo_pending and not library._photo_inflight
    assert not choice._pending


# ---------- choice._last_event(#516): 평가 초기화 목록 등록과 락 ----------
def test_reset_empties_the_choice_last_event_memory_and_the_other_choice_store():
    """'그거 지워줘'의 대상으로 기억해 둔 일정(`_last_event`, 10분 유지)이 다음 사례로 새지 않는다(합성 값만 쓴다)."""
    from app.features.schedule.agent import choice

    choice.remember_event("g-synthetic-1", "u-synthetic-1", "e-synthetic-1")
    choice.remember_event("g-synthetic-2", "u-synthetic-2", "e-synthetic-2")
    choice._pending[("g-synthetic-1", "u-synthetic-1")] = (9e18, None)
    assert choice.recall_event("g-synthetic-1", "u-synthetic-1") == "e-synthetic-1"
    env.reset_memory_state()
    assert not choice._last_event and not choice._pending
    assert choice.recall_event("g-synthetic-1", "u-synthetic-1") is None


def test_choice_last_event_is_registered_for_reset_with_the_lock_the_app_uses():
    key = ("app.features.schedule.agent.choice", "_last_event")
    assert key in env.MEMORY_RESETS
    assert env.MEMORY_LOCKS[key] == "_lock"
    assert env.MEMORY_LOCKS[("app.features.schedule.agent.choice", "_pending")] == "_lock"


def _reset_waits_for(lock, store, fill):
    """`lock` 을 쥔 동안 초기화가 기다리고(저장소가 그대로 남고), 락을 놓으면 끝나서 비우는지 본다."""
    import threading

    fill()
    done = threading.Event()

    def run():
        env.reset_memory_state()
        done.set()

    with lock:
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        assert not done.wait(0.3), "락을 쥐고 있는데 초기화가 먼저 끝났다(락 없이 비웠다)"
        assert store, "락을 쥐고 있는 동안 저장소가 비워졌다"
    assert done.wait(10), "락을 놓았는데 초기화가 끝나지 않았다(교착)"
    worker.join(10)
    assert not store


def test_reset_takes_the_choice_lock_so_it_cannot_race_a_request_touching_the_stores():
    from app.features.schedule.agent import choice

    _reset_waits_for(
        choice._lock,
        choice._last_event,
        lambda: choice.remember_event("g-synthetic", "u-synthetic", "e-synthetic"),
    )
    _reset_waits_for(
        choice._lock,
        choice._pending,
        lambda: choice._pending.__setitem__(("g-synthetic", "u-synthetic"), (9e18, None)),
    )


def test_a_store_with_the_default_lock_name_is_still_cleared_under_that_lock():
    """바꾸지 않은 동작: `<저장소 이름>_lock` 규칙(예: 일정 되묻기 초안 `ask._pending_lock`)도 그대로 락을 잡고 비운다."""
    from app.features.schedule.agent import ask

    _reset_waits_for(
        ask._pending_lock,
        ask._pending,
        lambda: ask._pending.__setitem__(("g-synthetic", "u-synthetic"), (9e18, None)),
    )


def test_every_explicit_lock_names_a_real_lock_for_a_registered_store():
    import importlib

    registered = set(env.MEMORY_RESETS)
    for (module_name, attr), lock_name in env.MEMORY_LOCKS.items():
        assert (module_name, attr) in registered
        lock = getattr(importlib.import_module(module_name), lock_name)
        assert hasattr(lock, "acquire") and hasattr(lock, "release")


def test_a_renamed_explicit_lock_stops_the_reset_instead_of_clearing_without_it(monkeypatch):
    monkeypatch.setitem(
        env.MEMORY_LOCKS, ("app.features.schedule.agent.choice", "_last_event"), "_no_such_lock"
    )
    with pytest.raises(AttributeError):
        env.reset_memory_state()


def test_reset_removes_uploads_but_keeps_model_files_and_stays_inside_the_root(root):
    from app.shared.config import settings

    data = Path(settings.data_dir)
    (data / "photos").mkdir(exist_ok=True)
    (data / "photos" / "a.jpg").write_bytes(b"x")
    (data / "models").mkdir(exist_ok=True)
    (data / "models" / "keep.bin").write_bytes(b"x")
    env.reset_data_files(root)
    assert not (data / "photos").exists() and (data / "models" / "keep.bin").exists()


def test_the_allowed_folder_must_be_a_subfolder_of_the_temp_directory(tmp_path):
    import tempfile

    for bad in (Path("data"), Path.cwd(), Path(tempfile.gettempdir()), Path.home()):
        with pytest.raises(UnsafeEnvironment, match="임시 폴더"):
            env.check_root(bad)
        with pytest.raises(UnsafeEnvironment):
            env.check_process_boundary(bad)
    env.check_root(tmp_path)


def test_a_raw_folder_outside_the_root_is_refused(root, tmp_path, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "raw_dir", str(tmp_path / "raw"))
    with pytest.raises(UnsafeEnvironment):
        env.check_process_boundary(root)


def test_a_session_factory_bound_to_another_engine_is_refused(root, tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from app.shared import db

    other = create_engine("sqlite:///" + str(tmp_path / "other.db"))
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": other})
    with pytest.raises(UnsafeEnvironment):
        env.check_process_boundary(root)
    other.dispose()


def test_settings_are_raised_inside_and_restored_after():
    from app.shared.config import settings

    names = [n for n in type(settings).model_fields if env._LIMIT_FIELD.fullmatch(n)]
    assert len(names) >= 8
    before = {n: getattr(settings, n) for n in names + ["web_search_enabled"]}
    settings.web_search_enabled = True
    with env.eval_settings():
        assert all(getattr(settings, n) == env.RAISED_LIMIT for n in names)
        assert settings.web_search_enabled is False
    assert settings.web_search_enabled is True
    assert {n: getattr(settings, n) for n in names} == {n: before[n] for n in names}
    settings.web_search_enabled = before["web_search_enabled"]


def test_the_process_context_blocks_the_network_and_fixes_the_clock_then_restores(root):
    import socket

    from app.features.billing import service

    with env.eval_process(root, now=datetime(2026, 3, 2, 12, tzinfo=UTC)):
        assert service.today_kst() == "2026-03-02"
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("push.example.com", 443)
    assert service.today_kst() != "2026-03-02"
    assert "DATABASE_URL" in os.environ  # 환경변수는 건드리지 않는다


def test_the_process_context_refuses_to_start_on_an_unsafe_database(tmp_path):
    with pytest.raises(UnsafeEnvironment), env.eval_process(tmp_path):
        pytest.fail("경계 확인 전에 평가가 시작되면 안 된다")


def test_nothing_leaks_after_the_process_context_so_normal_behavior_is_unchanged(root):
    """평가 환경을 열었다 닫으면 설정·소켓·모든 app 모듈의 시각 이름이 그대로여야 한다(꺼져 있으면 기존 동작과 같다)."""
    import socket
    import sys

    from app.shared.config import settings

    def snapshot():
        return (
            settings.model_dump(),
            (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex),
            {
                n: (getattr(m, "datetime", None), getattr(m, "date", None))
                for n, m in list(sys.modules.items())
                if n.startswith("app.") and m is not None
            },
        )

    before = snapshot()
    with env.eval_process(root):
        assert snapshot() != before
    with pytest.raises(ZeroDivisionError), env.eval_process(root):
        raise ZeroDivisionError
    assert snapshot() == before


def test_a_non_sqlite_url_is_refused_even_if_its_database_name_looks_like_a_path_inside_the_root(
    root,
):
    with pytest.raises(UnsafeEnvironment, match="SQLite"):
        check_database_url(f"postgresql://u@192.168.0.44/{(root / 'eval.db').as_posix()}", root)
