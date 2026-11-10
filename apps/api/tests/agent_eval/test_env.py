"""L2 실행 환경 시험(L0). 임시 SQLite 만 쓰고 가짜 모델도 부르지 않는다(DB·캐시·기억·일정 초안 초기화, 경계, 설정 복원)."""

import importlib
import os
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
    before = env.count_rows(engine)
    assert all(
        before[t] > 0
        for t in ("users", "groups", "events", "assistant_memories", "ai_result_cache")
    )
    assert ask._pending

    env.reset_case_state(root)

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


def test_only_the_known_in_memory_state_exists_in_the_agent_modules():
    """새 모듈 수준 가변 상태(캐시·초안 저장소)가 생기면 초기화 대상에서 빠지므로 여기서 알려 준다."""
    modules = [
        "app.features.schedule.agent.chat",
        "app.features.schedule.agent.handler",
        "app.features.schedule.agent.register",
        "app.features.schedule.agent.reader",
        "app.features.schedule.agent.suggest",
        "app.features.schedule.agent.ask",
        "app.features.billing.agent",
        "app.features.family_chat.agent",
        "app.features.ai_assistant.knowledge.rag_chat",
        "app.features.ai_assistant.memories",
        "app.features.ai_assistant.agents",
    ]
    constants = {  # 값이 바뀌지 않는 표(읽기 전용으로 쓰는 것)
        "SOURCES_BY_CHANNEL",
        "_MONTH_PROP",
        "_NO_ARGS",
        "_AFTER_BATCHIM",
        "_AFTER_OPEN",
        "AGENTS",
        "USAGE_FEATURES",
    }
    found = {
        f"{m}.{k}"
        for m in modules
        for k, v in vars(importlib.import_module(m)).items()
        if isinstance(v, dict | list | set) and not k.startswith("__") and k not in constants
    }
    assert found == {"app.features.schedule.agent.ask._pending"}  # reset_case_state 가 비운다


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
