"""DB 가 코드보다 뒤처지거나 앞서거나 연결이 안 될 때: 서버는 시작하고, 스키마가 준비되지 않은 기능만 503.

SQLite 로 스키마를 일부러 어긋나게 만들어 검증한다(실제 PostgreSQL 16 에서의 같은 흐름은
test_shared_db_deploy_e2e.py 의 자동 배포 통합 테스트).
"""

import shutil
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app
from app.shared import db
from app.shared import schema as schema_module
from app.shared.config import settings
from app.shared.db import Base, engine
from app.shared.schema import monitor, table_problems

API_ROOT = Path(__file__).resolve().parents[1]
BILLING_COLUMNS = ("settled_at", "settled_by")


@pytest.fixture(autouse=True)
def instant_recheck(monkeypatch):
    """테스트에서는 캐시 없이 바로 재점검한다."""
    monkeypatch.setattr(settings, "schema_recheck_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_recheck_not_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_force_min_interval_seconds", 0)
    monitor.reset()
    yield
    monitor.reset()
    # client 픽스처는 모델 테이블만 지운다 — 이 테스트들이 만든 alembic_version 이 다음 테스트에 남지 않게 한다
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def make_db_behind():
    """6304cb91e46a 이전 상태: billing_settings 테이블과 expenses.settled_* 컬럼이 없다."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE billing_settings"))
        for column in BILLING_COLUMNS:
            conn.execute(text(f"ALTER TABLE expenses DROP COLUMN {column}"))


def apply_migration():
    """마이그레이션 적용 완료: 빠진 테이블·컬럼이 생긴다(서버는 그대로)."""
    Base.metadata.tables["billing_settings"].create(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE expenses ADD COLUMN settled_at DATETIME"))
        conn.execute(text("ALTER TABLE expenses ADD COLUMN settled_by VARCHAR(32)"))


def set_revision(*revisions):
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        conn.execute(text("DELETE FROM alembic_version"))
        for revision in revisions:
            conn.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": revision})


def drop_revision_table():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def family_headers(family):
    return family[0]


def health(client):
    response = client.get("/health/db")
    assert response.status_code == 200
    return response.json()


# ---------- DB 가 코드보다 이전(뒤처짐) ----------
def test_behind_db_only_blocks_features_whose_schema_is_missing(client, family_headers):
    make_db_behind()
    set_revision("b6931fc30c66")

    blocked = client.get("/billing/expenses", headers=family_headers)
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "schema_not_ready" and set(blocked.json()) == {
        "code",
        "message",
    }
    assert blocked.headers["retry-after"] == "5"

    # 기존 DB 구조만 쓰는 API 는 그대로 동작한다 + 서버 자체는 살아 있다
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/family-group/me", headers=family_headers).status_code == 200
    assert client.get("/schedule/events", headers=family_headers).status_code == 200
    assert client.get("/family-chat/messages", headers=family_headers).status_code == 200

    report = health(client)
    assert report["status"] == "degraded" and report["revision_state"] == "behind"
    assert report["pending_revisions"] == pending_after("b6931fc30c66")
    assert report["features"]["billing"] == {"ready": False, "reason": "missing_schema"}
    assert report["features"]["schedule"] == {"ready": True, "reason": None}
    assert report["schema_ready"] is False


def test_server_starts_and_recovers_without_restart_after_migration(client, family_headers):
    make_db_behind()
    set_revision("b6931fc30c66")
    assert client.get("/billing/expenses", headers=family_headers).status_code == 503

    apply_migration()  # 자동 배포가 끝남 — 서버는 재시작하지 않는다
    set_revision(schema_head())
    assert client.get("/billing/expenses", headers=family_headers).status_code == 200
    report = health(client)
    assert report["status"] == "ready" and report["revision_state"] == "ready"
    assert report["pending_revisions"] == [] and report["db_revision"] == report["code_head"]


def pending_after(revision):
    """코드 이력에서 revision 다음부터 head 까지(오래된 것부터). main 에 리비전이 늘어도 맞도록 코드에서 계산한다."""
    cfg = Config()
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    chain = [r.revision for r in script.iterate_revisions(script.get_current_head(), revision)]
    return [r for r in chain if r != revision][::-1]


def schema_head():
    cfg = Config()
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


# ---------- DB 가 코드보다 앞섬 / 알 수 없는 리비전 ----------
def test_ahead_db_is_not_assumed_compatible_but_passes_when_the_probe_passes(
    client, family_headers
):
    set_revision("ffffffffffff")  # 이 코드가 모르는 리비전
    report = health(client)
    assert (
        report["revision_state"] == "ahead_or_unknown" and report["db_revision"] == "ffffffffffff"
    )
    assert report["status"] == "degraded"  # 호환을 '가정'하지 않고 상태는 경고로 표시
    assert (
        client.get("/billing/expenses", headers=family_headers).status_code == 200
    )  # 실제 스키마가 맞으면 허용


def test_ahead_db_missing_a_column_the_code_needs_is_blocked(client, family_headers):
    set_revision("ffffffffffff")
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE events DROP COLUMN source")
        )  # 앞선 마이그레이션이 컬럼을 없앤 경우
    assert client.get("/schedule/events", headers=family_headers).status_code == 503
    assert client.get("/billing/expenses", headers=family_headers).status_code == 200


def test_unknown_revision_with_incompatible_core_blocks_every_feature(client, family_headers):
    set_revision("ffffffffffff")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE group_members DROP COLUMN joined_at"))
    for path in ("/family-group/me", "/billing/expenses", "/schedule/events"):
        assert client.get(path, headers=family_headers).status_code == 503, path


# ---------- 리비전 상태 안전 처리 ----------
def test_revision_states_are_reported_safely(client):
    drop_revision_table()
    assert health(client)["revision_state"] == "not_applicable"  # SQLite 는 Alembic 을 쓰지 않음

    set_revision()  # 행이 없음
    assert health(client)["revision_state"] == "no_revision"
    set_revision("b6931fc30c66", "6304cb91e46a")  # 행이 둘
    assert health(client)["revision_state"] == "invalid_revision_state"
    set_revision("ffffffffffff")
    assert health(client)["revision_state"] == "ahead_or_unknown"
    set_revision("355a1a748ec5")
    report = health(client)
    assert report["revision_state"] == "behind" and report["pending_revisions"][0] == "9e28d84c1686"


def test_multiple_code_heads_are_reported_and_never_treated_as_ready(
    client, family_headers, tmp_path, monkeypatch
):
    dest = tmp_path / "alembic"
    shutil.copytree(API_ROOT / "alembic", dest, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "versions" / "c1_branch.py").write_text(
        '"""branch"""\nrevision = "c1"\ndown_revision = "9e28d84c1686"\nbranch_labels = None\ndepends_on = None\n\n\ndef upgrade():\n    pass\n',
        encoding="utf-8",
    )
    cfg = Config()
    cfg.set_main_option("script_location", str(dest))
    monkeypatch.setattr(db, "_script_directory", lambda: ScriptDirectory.from_config(cfg))
    set_revision("6304cb91e46a")
    report = health(client)
    assert report["revision_state"] == "multiple_heads" and len(report["code_heads"]) == 2
    assert (
        report["code_head"] is None
        and report["schema_ready"] is False
        and report["status"] == "degraded"
    )
    assert (
        client.get("/billing/expenses", headers=family_headers).status_code == 200
    )  # 기능은 실제 스키마로 판단


def test_broken_alembic_history_is_reported_as_code_error(client, monkeypatch):
    def broken():
        raise RuntimeError("순환 참조")

    monkeypatch.setattr(db, "_script_directory", broken)
    report = health(client)
    assert report["revision_state"] == "code_error" and report["error"] == "RuntimeError"


# ---------- DB 연결 실패 ----------
def test_db_connection_failure_keeps_server_up_and_returns_503_without_leaking_secrets(monkeypatch):
    secret = "SuperSecretPw123"
    dead = create_engine(
        f"postgresql+psycopg://gabee_app:{secret}@127.0.0.1:1/gabee",
        connect_args={"connect_timeout": 2},
    )
    monkeypatch.setattr(db, "engine", dead)
    monkeypatch.setattr(schema_module.db, "engine", dead)
    with TestClient(app) as client:  # 시작(lifespan)이 실패하지 않아야 한다
        assert client.get("/health").json() == {"status": "ok"}
        blocked = client.get("/family-group/me")
        assert blocked.status_code == 503 and blocked.json()["code"] == "db_unavailable"
        assert blocked.headers["retry-after"] == "5"
        response = client.get("/health/db")
        assert response.status_code == 200
        report = response.json()
        assert report["status"] == "unavailable" and report["db_connected"] is False
        assert (
            report["revision_state"] == "db_unavailable" and report["error"] == "OperationalError"
        )
        for leaked in (secret, "gabee_app", "127.0.0.1", "postgresql+psycopg"):
            assert leaked not in response.text
    monitor.reset()


# ---------- 상태 확인 API ----------
def test_health_db_reports_ready_state_and_exposes_no_internal_names(client):
    report = health(client)
    assert (
        report["status"] == "ready"
        and report["db_connected"] is True
        and report["dialect"] == "sqlite"
    )
    assert set(report) == {
        "status", "db_connected", "dialect", "db_revision", "code_head", "code_heads", "revision_state",
        "pending_revisions", "schema_ready", "features", "error", "checked_at",
    }  # fmt: skip
    assert set(report["features"]) == {
        "family_group",
        "family_chat",
        "schedule",
        "schedule_check",
        "billing",
        "ai_assistant",
        "notifications",
        "support",
    }
    assert "problems" not in str(report) and "expenses" not in str(
        report
    )  # 테이블·컬럼 이름 비노출


# ---------- 점검 규칙(단위) ----------
class FakeInspector:
    def __init__(self, columns, exists=True):
        self.columns, self.exists = columns, exists

    def has_table(self, name):
        return self.exists

    def get_columns(self, name):
        return self.columns


def column(name, nullable=True, default=None, **extra):
    return {"name": name, "nullable": nullable, "default": default, **extra}


def test_table_problems_flags_what_would_break_this_codes_inserts():
    table = Base.metadata.tables["expenses"]
    ok = [column(c.name, c.nullable, "x" if not c.nullable else None) for c in table.columns]
    assert table_problems(FakeInspector(ok), table) == []

    extra_required = [
        *ok,
        column("new_required", nullable=False),
    ]  # 코드가 모르는 NOT NULL, 기본값 없음
    assert "코드가 모르는 NOT NULL" in table_problems(FakeInspector(extra_required), table)[0]

    extra_with_default = [*ok, column("new_required", nullable=False, default="0")]
    assert table_problems(FakeInspector(extra_with_default), table) == []

    extra_optional = [*ok, column("new_optional", nullable=True)]
    assert table_problems(FakeInspector(extra_optional), table) == []

    missing = [c for c in ok if c["name"] != "date"]
    assert "컬럼 expenses.date 없음" in table_problems(FakeInspector(missing), table)

    assert table_problems(FakeInspector([], exists=False), table) == ["테이블 expenses 없음"]


def test_nullable_column_tightened_to_not_null_is_incompatible_unless_defaulted():
    table = Base.metadata.tables["billing_settings"]
    tightened = [
        column(c.name, nullable=False) for c in table.columns
    ]  # 모델은 nullable 인 컬럼이 있다면 충돌
    nullable_in_model = [c.name for c in table.columns if c.nullable]
    problems = table_problems(FakeInspector(tightened), table)
    assert len(problems) == len(nullable_in_model)


def test_shared_model_table_missing_blocks_the_features_that_use_it(client, family_headers):
    """app/shared 의 공통 모델(위치 동의 이력)이 없으면 그것을 쓰는 가입(family_group)을 연다고 보지 않는다."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE location_consent_events"))
    report = health(client)
    assert report["features"]["family_group"]["ready"] is False
    assert client.get("/family-group/me", headers=family_headers).status_code == 503


# ---------- 데일리 체크 하위 기능(schedule_check): 날짜별 기록 테이블과 소프트 삭제 컬럼 ----------
def test_check_log_table_missing_blocks_only_check_api(client, family_headers):
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE events_check_logs"))
    try:
        blocked = client.get("/schedule/check/items", headers=family_headers)
        assert blocked.status_code == 503 and blocked.json()["code"] == "schema_not_ready"
        assert client.get("/schedule/events", headers=family_headers).status_code == 200
        report = health(client)
        assert report["features"]["schedule_check"]["ready"] is False
        assert report["features"]["schedule"]["ready"] is True
    finally:
        Base.metadata.tables["events_check_logs"].create(engine, checkfirst=True)
    assert client.get("/schedule/check/items", headers=family_headers).status_code == 200


def test_check_item_deleted_at_missing_blocks_only_check_api(client, family_headers):
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE events_check_items DROP COLUMN deleted_at"))
    try:
        blocked = client.get("/schedule/check/items", headers=family_headers)
        assert blocked.status_code == 503 and blocked.json()["code"] == "schema_not_ready"
        assert client.get("/schedule/events", headers=family_headers).status_code == 200
        assert health(client)["features"]["schedule_check"]["ready"] is False
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE events_check_items ADD COLUMN deleted_at DATETIME"))
    assert client.get("/schedule/check/items", headers=family_headers).status_code == 200


def test_check_log_table_is_part_of_schedule_check_feature():
    from app.shared.schema import feature_tables

    assert "events_check_logs" in feature_tables()["schedule_check"]
