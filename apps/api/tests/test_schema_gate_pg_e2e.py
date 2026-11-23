"""PostgreSQL 16 에서의 스키마 게이트 통합 테스트(실제 Alembic 마이그레이션 사용).

Docker 가 필요하므로 GABEE_PG16_E2E=1 일 때만 실행한다(CI 기본 실행에서는 건너뜀).
이 테스트가 직접 띄운 임시 컨테이너만 사용한다 — 공용 DB·개인 DB·MVP DB 에는 접속하지 않는다.
"""

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app
from app.shared import db as app_db
from app.shared.config import settings
from app.shared.schema import monitor

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_PG16_E2E") != "1", reason="GABEE_PG16_E2E=1 일 때만 실행(Docker 필요)"
)

API_ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pgvector/pgvector:pg16"
SCRIPT = ScriptDirectory.from_config(
    (lambda cfg: (cfg.set_main_option("script_location", str(API_ROOT / "alembic")), cfg)[1])(
        Config()
    )
)
HEAD = SCRIPT.get_current_head()
_PARENTS = SCRIPT.get_revision(
    HEAD
).down_revision  # 방금 병합됐지만 아직 DB 에 적용되지 않은 최신 마이그레이션 직전
# 최신 리비전이 두 head 를 합치는 병합 리비전이면 부모가 둘이다(튜플). 그때 뒤처진 DB 는 두 갈래 중 한 갈래만 적용한 DB 다
# (두 부모가 모두 `alembic_version` 에 따로 있는 상태는 서버가 invalid_revision_state 로 보는 상태이고 배포가 병합 리비전으로 합친다)
BEFORE_HEAD = _PARENTS[0] if isinstance(_PARENTS, (tuple, list)) else _PARENTS
# BEFORE_HEAD 에서 HEAD 까지 적용 대기 중인 리비전(서버가 알려 주는 순서: 오래된 것부터)
EXPECTED_PENDING = [
    r.revision for r in SCRIPT.iterate_revisions(HEAD, BEFORE_HEAD) if r.revision != BEFORE_HEAD
][::-1]
# 이 DB 에 아직 없는 마이그레이션 전부(병합 리비전이면 DB 가 적용하지 않은 다른 갈래의 리비전도 든다. 서버의 '대기 리비전' 목록에는
# 다른 갈래가 안 보이지만 그 갈래의 테이블이 없으면 해당 기능은 막힌다)
_MISSING = {r.revision for r in SCRIPT.iterate_revisions(HEAD, "base")} - {
    r.revision for r in SCRIPT.iterate_revisions(BEFORE_HEAD, "base")
}
# 그 마이그레이션들이 코드가 쓰는 스키마를 추가하는지(삭제 전용이면 DB 가 뒤처져도 막히는 기능이 없다)
HEAD_ADDS_SCHEMA = any(
    marker
    in Path(SCRIPT.get_revision(rev).path).read_text(encoding="utf-8").split("def downgrade")[0]
    for rev in _MISSING
    for marker in ("op.create_table", "op.add_column", "op.create_index", "op.alter_column")
)
HEADERS = {"X-Gyeot-Token": "t1"}
EXISTING = (
    "/family-group/me",
    "/schedule/events",
    "/notifications",
    "/family-chat/messages",
)


def docker(*args, check=True, env=None):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, encoding="utf-8", check=check, env=env
    )


@pytest.fixture(scope="module")
def pg16():
    name, password = f"gabee-gate-e2e-{secrets.token_hex(3)}", secrets.token_urlsafe(12)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-e",
        "POSTGRES_PASSWORD",
        "-p",
        "127.0.0.1::5432",
        IMAGE,
        env=env,
    )
    try:
        for _ in range(60):
            if (
                docker(
                    "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", check=False
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        time.sleep(2)
        port = int(
            docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        )
        yield {"port": port, "password": password}
    finally:
        docker("rm", "-f", name, check=False)


def admin(pg, dbname="gabee"):
    return psycopg.connect(
        host="127.0.0.1",
        port=pg["port"],
        dbname=dbname,
        user="postgres",
        password=pg["password"],
        autocommit=True,
    )


def url(pg):
    return f"postgresql+psycopg://postgres:{pg['password']}@127.0.0.1:{pg['port']}/gabee"


def create_db(pg):
    with admin(pg, "postgres") as c:
        c.execute("DROP DATABASE IF EXISTS gabee WITH (FORCE)")
        c.execute("CREATE DATABASE gabee")
    with admin(pg) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")


def migrate(pg, revision):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env["DATABASE_URL"] = url(pg)
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr[-500:]


def seed(pg):
    with admin(pg) as c:
        c.execute(
            "INSERT INTO users (id, name, role, token, active_group_id, created_at) VALUES ('u1','지민','parent','t1','g1',now())"
        )
        c.execute(
            "INSERT INTO groups (id, name, owner_id, created_at) VALUES ('g1','가족','u1',now())"
        )
        c.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES ('g1','u1','owner',now())"
        )


def build(pg, revision):
    create_db(pg)
    migrate(pg, revision)
    seed(pg)


@pytest.fixture
def start_app(pg16, monkeypatch):
    """실제 FastAPI 앱을 임시 PostgreSQL 16 에 붙여 시작한다(시작 시점의 DB 상태는 호출한 테스트가 정한다)."""
    engines = []
    original = app_db.engine
    for name in (
        "schema_recheck_ready_seconds",
        "schema_recheck_not_ready_seconds",
        "schema_force_min_interval_seconds",
    ):
        monkeypatch.setattr(settings, name, 0)
    stack = []

    def start():
        pg_engine = create_engine(
            url(pg16), connect_args={"connect_timeout": 3}, pool_pre_ping=True
        )
        engines.append(pg_engine)
        monkeypatch.setattr(app_db, "engine", pg_engine)
        app_db.SessionLocal.configure(bind=pg_engine)
        monitor.reset()
        client = TestClient(app)
        client.__enter__()  # lifespan(init_db): DB 가 뒤처졌거나 없어도 실패하지 않아야 한다
        stack.append(client)
        return client

    yield start
    for client in stack:
        client.__exit__(None, None, None)
    app_db.SessionLocal.configure(bind=original)
    monitor.reset()
    for engine in engines:
        engine.dispose()


def codes(client, paths=EXISTING):
    return [client.get(path, headers=HEADERS).status_code for path in paths]


def health(client):
    return client.get("/health/db").json()


def test_server_starts_one_migration_behind_and_opens_after_upgrade_without_restart(
    pg16, start_app
):
    build(pg16, BEFORE_HEAD)
    client = start_app()  # DB 가 코드보다 한 마이그레이션 뒤처진 상태로 서버 시작

    assert client.get("/health").json() == {"status": "ok"}
    report = health(client)
    assert report["db_connected"] is True and report["revision_state"] == "behind"
    assert report["pending_revisions"] == EXPECTED_PENDING and report["status"] == "degraded"
    assert EXPECTED_PENDING[-1] == HEAD
    assert pg16["password"] not in client.get("/health/db").text

    # 최신 마이그레이션이 무엇을 바꾸는지에 의존하지 않는다: 코드가 필요로 하는 스키마가 아직 없는 기능만 막힌다
    not_ready = {name for name, f in report["features"].items() if not f["ready"]}
    if HEAD_ADDS_SCHEMA:
        assert not_ready, "대기 중인 마이그레이션의 스키마를 쓰는 기능이 막혀 있어야 한다"
    else:
        # 삭제 전용 마이그레이션은 코드가 쓰는 스키마를 늘리지 않으므로 뒤처져도 막히는 기능이 없다
        assert not not_ready, f"삭제 전용 마이그레이션인데 막힌 기능이 있다: {sorted(not_ready)}"
    checked = {
        "family_group": "/family-group/me",
        "schedule": "/schedule/events",
        "notifications": "/notifications",
        "family_chat": "/family-chat/messages",
        "billing": "/billing/expenses",
    }
    for feature, path in checked.items():
        response = client.get(path, headers=HEADERS)
        if feature in not_ready or "family_group" in not_ready:
            assert response.status_code == 503, path
            assert response.json()["code"] == "schema_not_ready"
            assert response.headers["retry-after"] == "5"
        else:
            assert response.status_code == 200, path  # 준비된 기능은 영향이 없다

    migrate(pg16, "head")  # 마이그레이션(자동 배포) 완료 — 서버는 재시작하지 않는다
    assert codes(client) == [200, 200, 200, 200]
    ready = health(client)
    assert ready["status"] == "ready" and ready["db_revision"] == ready["code_head"] == HEAD
    assert ready["pending_revisions"] == []


def test_server_starts_without_database_then_recovers_when_it_appears(pg16, start_app):
    with admin(pg16, "postgres") as c:
        c.execute("DROP DATABASE IF EXISTS gabee WITH (FORCE)")
    client = start_app()  # DB 자체가 없어 연결 실패 — 서버는 시작해야 한다
    assert client.get("/health").json() == {"status": "ok"}
    report = health(client)
    assert report["status"] == "unavailable" and report["db_connected"] is False
    assert report["error"] == "OperationalError" and pg16["password"] not in str(report)
    blocked = client.get("/family-group/me", headers=HEADERS)
    assert blocked.status_code == 503 and blocked.json()["code"] == "db_unavailable"

    build(pg16, "head")  # DB 가 준비됨 — 서버 재시작 없이 회복
    assert codes(client) == [200, 200, 200, 200]
    assert health(client)["status"] == "ready"


def test_only_the_feature_with_missing_schema_is_blocked(pg16, start_app):
    build(pg16, "head")
    client = start_app()
    assert (
        codes(client) == [200, 200, 200, 200]
        and client.get("/billing/expenses", headers=HEADERS).status_code == 200
    )
    with admin(pg16) as c:  # 새 스키마가 필요한 가계 쪽만 이전 상태로 되돌린 것처럼 만든다
        c.execute("ALTER TABLE expenses DROP COLUMN settled_by")
    assert codes(client) == [200, 200, 200, 200]  # 기존 구조만 쓰는 API 는 그대로
    assert client.get("/billing/expenses", headers=HEADERS).status_code == 503
    assert health(client)["features"]["billing"] == {"ready": False, "reason": "missing_schema"}
    with admin(pg16) as c:
        c.execute("ALTER TABLE expenses ADD COLUMN settled_by VARCHAR(32)")
    assert client.get("/billing/expenses", headers=HEADERS).status_code == 200


def test_db_ahead_of_code_is_verified_by_the_real_schema(pg16, start_app):
    build(pg16, "head")
    client = start_app()
    with admin(pg16) as c:
        c.execute(
            "UPDATE alembic_version SET version_num = 'ffffffffffff'"
        )  # 이 코드가 모르는 리비전
    report = health(client)
    assert report["revision_state"] == "ahead_or_unknown" and report["status"] == "degraded"
    assert codes(client) == [200, 200, 200, 200]  # 실제 스키마가 호환되면 허용

    with admin(
        pg16
    ) as c:  # 코드가 모르는 NOT NULL + 기본값 없는 컬럼 → 이 코드의 INSERT 가 깨지므로 일정 차단
        c.execute("ALTER TABLE events ADD COLUMN must_have text NOT NULL DEFAULT 'x'")
        c.execute("ALTER TABLE events ALTER COLUMN must_have DROP DEFAULT")
    assert codes(client) == [200, 503, 200, 200]
    assert health(client)["features"]["schedule"] == {
        "ready": False,
        "reason": "incompatible_schema",
    }

    with admin(pg16) as c:  # 가입·그룹 쪽(모든 기능의 전제)이 깨지면 전부 차단하되 서버는 살아 있다
        c.execute("ALTER TABLE group_members DROP COLUMN joined_at")
    assert codes(client) == [503, 503, 503, 503]
    assert client.get("/health").json() == {"status": "ok"}


def test_shared_common_model_table_is_part_of_the_feature_check(pg16, start_app):
    build(pg16, "head")
    client = start_app()
    with admin(pg16) as c:
        c.execute("DROP TABLE location_consent_events")
    assert health(client)["features"]["family_group"]["ready"] is False
    assert client.get("/family-group/me", headers=HEADERS).status_code == 503
