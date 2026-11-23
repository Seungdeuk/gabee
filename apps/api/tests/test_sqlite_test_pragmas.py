"""임시 SQLite 속도 설정(`tests/sqlite_pragmas.py`) 시험: 적용 범위·실제 값·트랜잭션·격리·초기화/정리 동작."""

import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import db as shared_db
from app.shared.db import Base, SessionLocal, engine, init_db
from tests import sqlite_pragmas

TEMP_DIR = Path(os.environ["DATA_DIR"])


def _pragma(conn, name):
    return conn.execute(text(f"PRAGMA {name}")).scalar()


# ---- 적용 범위: 임시 DB 에만 ---------------------------------------------------------------------------------------------
def test_the_app_engine_is_the_pytest_temp_sqlite_file():
    assert engine.dialect.name == "sqlite"
    assert Path(engine.url.database).resolve() == (TEMP_DIR / "test.db").resolve()
    assert TEMP_DIR.name.startswith("gabee-test-")
    assert TEMP_DIR.resolve().parent == Path(tempfile.gettempdir()).resolve()
    assert os.environ["DATABASE_URL"] == f"sqlite:///{TEMP_DIR}/test.db"
    assert sqlite_pragmas.is_pytest_temp_sqlite(str(engine.url), TEMP_DIR)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@db.example/gabee",  # 운영·공용 PostgreSQL
        "postgresql://u:p@192.168.0.44:5432/gabee",
        "sqlite:///./gabee.db",  # 개발 PC 의 로컬 SQLite
        "sqlite:///C:/Users/someone/gabee.db",
        "sqlite://",  # 메모리 DB
        "not a url",
    ],
)
def test_the_guard_refuses_anything_that_is_not_the_pytest_temp_file(url):
    assert sqlite_pragmas.is_pytest_temp_sqlite(url, TEMP_DIR) is False


def test_the_guard_refuses_other_files_even_inside_the_temp_folder_or_another_temp_folder(tmp_path):
    assert not sqlite_pragmas.is_pytest_temp_sqlite(f"sqlite:///{TEMP_DIR}/other.db", TEMP_DIR)
    # 임시 폴더 안이어도 이름이 gabee-test- 로 시작하지 않으면 거부한다
    assert not sqlite_pragmas.is_pytest_temp_sqlite(f"sqlite:///{tmp_path}/test.db", tmp_path)
    # 임시 폴더 밖의 gabee-test-* 도 거부한다(시스템 임시 폴더 바로 아래만 허용)
    outside = Path(tempfile.gettempdir()).resolve().parent / "gabee-test-x"
    assert not sqlite_pragmas.is_pytest_temp_sqlite(f"sqlite:///{outside}/test.db", outside)


def test_apply_does_nothing_for_other_engines(tmp_path):
    other = create_engine(f"sqlite:///{tmp_path}/other.db")
    try:
        assert sqlite_pragmas.apply(other, tmp_path) is False
        with other.connect() as conn:
            assert _pragma(conn, "journal_mode") == "delete"
            assert _pragma(conn, "synchronous") == 2  # FULL(SQLite 기본값)
    finally:
        other.dispose()


def test_an_unrelated_sqlite_connection_keeps_the_defaults(tmp_path):
    raw = sqlite3.connect(tmp_path / "unrelated.db")
    try:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert raw.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        raw.close()


# ---- 실제 PRAGMA 적용값 -----------------------------------------------------------------------------------------------------
def test_the_pragmas_are_applied_to_every_new_connection_of_the_app_engine():
    engine.dispose()  # 연결을 새로 만들게 한다
    for _ in range(2):
        with engine.connect() as conn:
            assert _pragma(conn, "journal_mode") == "memory"
            assert _pragma(conn, "synchronous") == 0  # OFF
    with engine.connect() as first, engine.connect() as second:  # 풀에서 동시에 연 두 연결 모두
        for conn in (first, second):
            assert _pragma(conn, "journal_mode") == "memory"
            assert _pragma(conn, "synchronous") == 0


def test_the_pragma_settings_are_the_documented_ones():
    assert sqlite_pragmas.PRAGMAS == (("journal_mode", "MEMORY"), ("synchronous", "OFF"))


# ---- 트랜잭션·격리·초기화·정리 ---------------------------------------------------------------------------------------------
@pytest.fixture
def tables():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _user(name):
    return User(id=uuid.uuid4().hex[:12], name=name, token=uuid.uuid4().hex)


def test_commit_persists_and_rollback_discards(tables):
    with SessionLocal() as db:
        db.add(_user("커밋"))
        db.commit()
    with SessionLocal() as db:
        db.add(_user("롤백"))
        db.flush()
        db.rollback()
    with SessionLocal() as db:
        assert [u.name for u in db.query(User).order_by(User.name)] == ["커밋"]


def test_an_uncommitted_write_is_invisible_to_other_connections(tables):
    writer = SessionLocal()
    try:
        writer.add(_user("미커밋"))
        writer.flush()
        with SessionLocal() as reader:
            assert reader.query(User).count() == 0
        writer.rollback()
    finally:
        writer.close()


def test_committed_data_survives_closing_every_connection(tables):
    with SessionLocal() as db:
        db.add(_user("유지"))
        db.commit()
    engine.dispose()  # 연결을 모두 닫고 파일에서 다시 읽는다
    with SessionLocal() as db:
        assert [u.name for u in db.query(User)] == ["유지"]


def test_an_error_inside_a_transaction_rolls_back_the_whole_unit(tables):
    with pytest.raises(RuntimeError):
        with Session(engine) as db, db.begin():
            db.add(_user("실패"))
            db.flush()
            raise RuntimeError("boom")
    with SessionLocal() as db:
        assert db.query(User).count() == 0


def test_drop_all_then_init_db_gives_an_empty_schema_every_time(tables):
    with SessionLocal() as db:
        db.add(_user("지워질 사람"))
        db.commit()
    Base.metadata.drop_all(engine)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall() == []
        )
    init_db()  # `client` 픽스처의 앱 시작과 같은 초기화
    init_db()  # 여러 번 불러도 안전하다
    with SessionLocal() as db:
        assert db.query(User).count() == 0
    with engine.connect() as conn:
        names = {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert set(Base.metadata.tables) <= names


def test_the_client_fixture_starts_and_cleans_up_with_the_fast_settings(client):
    """실제 `client` 픽스처 경로: 앱 시작(init_db) 뒤 요청이 되고, 연결에는 속도 설정이 적용돼 있다."""
    assert client.get("/health").status_code == 200
    with engine.connect() as conn:
        assert _pragma(conn, "journal_mode") == "memory"
        assert (
            conn.execute(text("SELECT count(*) FROM sqlite_master WHERE type='table'")).scalar() > 0
        )


def test_the_previous_test_left_no_tables_behind():
    """바로 앞 시험의 `client` 픽스처 정리(drop_all)가 끝난 뒤 테이블이 남지 않는다(시험 간 격리)."""
    with engine.connect() as conn:
        left = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    assert left == []


def test_the_module_level_engine_is_the_one_the_app_uses():
    assert shared_db.engine is engine
