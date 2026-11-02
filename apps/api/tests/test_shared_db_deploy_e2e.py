"""공용 DB 자동 배포 전체 흐름 e2e — 격리된 PostgreSQL 16 컨테이너를 '가짜 공용 DB'로 쓴다.

Docker 가 필요하므로 GABEE_DEPLOY_E2E=1 일 때만 실행한다(CI 기본 실행에서는 건너뜀).
실제 공용 DB(192.168.0.44)·개인 DB·MVP DB 에는 접속하지 않는다: 대상은 이 테스트가 만든 컨테이너뿐이다.
"""

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import threading
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
    os.environ.get("GABEE_DEPLOY_E2E") != "1", reason="GABEE_DEPLOY_E2E=1 일 때만 실행(Docker 필요)"
)

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "scripts"))
import shared_db_deploy as deploy  # noqa: E402

SHA = "c" * 40
IMAGE = "pgvector/pgvector:pg16"
PRIOR = "b6931fc30c66"  # 배포 전 공용 DB 가 있던 리비전(이후 마이그레이션이 대기 중인 상태)


def _script():
    cfg = Config()
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


HEAD = _script().get_current_head()  # main 에 리비전이 늘어도 맞도록 코드에서 계산한다


def pending_after(revision):
    script = _script()
    chain = [r.revision for r in script.iterate_revisions(HEAD, revision)]
    return [r for r in chain if r != revision][::-1]


class FakeCi:
    status = "ok"

    def verify(self, sha):
        return deploy.CiVerdict(self.status, "fake")


def docker(*args, check=True, env=None):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, encoding="utf-8", check=check, env=env
    )


@pytest.fixture(scope="module")
def fake_shared(tmp_path_factory):
    suffix = secrets.token_hex(3)
    network, name = f"gabee-e2e-net-{suffix}", f"gabee-e2e-db-{suffix}"
    admin_pw, migrator_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    docker("network", "create", network)
    env = {**os.environ, "POSTGRES_PASSWORD": admin_pw}
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "--network",
        network,
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
            subprocess.run(["python", "-c", "import time; time.sleep(1)"])
        port = int(
            docker("port", name, "5432/tcp").stdout.strip().splitlines()[0].rsplit(":", 1)[1]
        )
        admin = dict(
            host="127.0.0.1", port=port, user="postgres", password=admin_pw, autocommit=True
        )
        import time

        time.sleep(2)
        with psycopg.connect(dbname="postgres", **admin) as c:
            c.execute(f"CREATE ROLE gabee_migrator LOGIN PASSWORD '{migrator_pw}'")
            c.execute(f"CREATE ROLE gabee_app LOGIN PASSWORD '{secrets.token_urlsafe(12)}'")
        pgpass = tmp_path_factory.mktemp("pgpass") / "pgpass"
        pgpass.write_text(
            f"127.0.0.1:{port}:gabee:gabee_migrator:{migrator_pw}\n{name}:5432:gabee:gabee_migrator:{migrator_pw}\n",
            encoding="utf-8",
        )
        target = deploy.Target(
            "127.0.0.1",
            port,
            "gabee",
            "gabee_migrator",
            tools_host=name,
            tools_port=5432,
            docker_network=network,
        )
        yield {
            "admin": admin,
            "target": target,
            "pgpass": pgpass,
            "migrator_pw": migrator_pw,
            "port": port,
        }
    finally:
        docker("rm", "-f", name, check=False)
        docker("network", "rm", network, check=False)


def alembic(fs, *args):
    url = f"postgresql+psycopg://gabee_migrator:{fs['migrator_pw']}@127.0.0.1:{fs['port']}/gabee"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"}
    env["DATABASE_URL"] = url
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr[-500:]


def conn(fs, **kw):
    t = fs["target"]
    return psycopg.connect(
        host=t.host,
        port=t.port,
        dbname="gabee",
        user="gabee_migrator",
        password=fs["migrator_pw"],
        autocommit=True,
        **kw,
    )


def reset_db(fs, stage="prior"):
    with psycopg.connect(dbname="postgres", **fs["admin"]) as c:
        c.execute("DROP DATABASE IF EXISTS gabee WITH (FORCE)")
        c.execute("CREATE DATABASE gabee OWNER gabee_migrator")
    with psycopg.connect(dbname="gabee", **fs["admin"]) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("GRANT CONNECT ON DATABASE gabee TO gabee_app")
        c.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE gabee_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gabee_app"
        )
        c.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE gabee_migrator IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO gabee_app"
        )
    alembic(fs, "upgrade", PRIOR)
    with conn(fs) as c:
        c.execute(
            "INSERT INTO users (id, name, role, token, active_group_id, created_at) VALUES ('u1','지민','parent','t1','g1',now()),('u2','수진','child','t2','g1',now())"
        )
        c.execute(
            "INSERT INTO groups (id, name, owner_id, created_at) VALUES ('g1','가족','u1',now())"
        )
        c.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES ('g1','u1','owner',now()),('g1','u2','member',now())"
        )
        c.execute(
            "INSERT INTO invites (code, group_id, created_by, id, revoked, use_count, created_at) VALUES ('ABCDEFGH','g1','u1','i1',false,0,now())"
        )
    if stage == "head":
        alembic(fs, "upgrade", "head")


def revision_of(fs):
    with conn(fs) as c:
        return [r[0] for r in c.execute("SELECT version_num FROM alembic_version").fetchall()]


def counts(fs):
    with conn(fs) as c:
        return [
            c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("users", "groups", "group_members", "invites")
        ]


def tables(fs):
    with conn(fs) as c:
        return {
            r[0]
            for r in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()
        }


def restore_into_fresh_pg16(dump: Path) -> dict:
    """산출된 백업을 완전히 새 PostgreSQL 16 컨테이너에 복원해 내용을 읽는다(배포기와 별개의 독립 검증)."""
    name, password = f"gabee-e2e-restore-{secrets.token_hex(3)}", secrets.token_urlsafe(12)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    docker(
        "run",
        "-d",
        "--rm",
        "--name",
        name,
        "-e",
        "POSTGRES_PASSWORD",
        "-e",
        "POSTGRES_USER=restore",
        "-e",
        "POSTGRES_DB=restore",
        IMAGE,
        env=env,
    )
    try:
        for _ in range(60):
            if (
                docker(
                    "exec",
                    name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "restore",
                    "-d",
                    "restore",
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        time.sleep(2)
        docker("cp", str(dump), f"{name}:/tmp/r.dump")
        docker(
            "exec",
            name,
            "pg_restore",
            "-U",
            "restore",
            "-d",
            "restore",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "/tmp/r.dump",
        )

        def q(sql):
            return docker(
                "exec", name, "psql", "-U", "restore", "-d", "restore", "-At", "-c", sql
            ).stdout.strip()

        return {
            "version": int(q("SHOW server_version_num")) // 10000,
            "revision": q("SELECT version_num FROM alembic_version"),
            "counts": [
                int(q(f"SELECT count(*) FROM {t}"))
                for t in ("users", "groups", "group_members", "invites")
            ],
            "vector": q("SELECT count(*) FROM pg_extension WHERE extname='vector'"),
        }
    finally:
        docker("rm", "-f", name, check=False)


def deployer(fs, tmp_path, ci=None, **kw):
    kw.setdefault("backup_dir", tmp_path / "backups")
    return deploy.Deployer(
        target=fs["target"], trusted_targets=(fs["target"],), sha=SHA, state_dir=tmp_path / "state",
        pgpass=fs["pgpass"], ci_verifier=ci or FakeCi(), verify_checkout=False, **kw,
    )  # fmt: skip


def alembic_copy(tmp_path, files):
    dest = tmp_path / "alembic"
    shutil.copytree(API_ROOT / "alembic", dest, ignore=shutil.ignore_patterns("__pycache__"))
    for name, text in files.items():
        (dest / "versions" / name).write_text(text, encoding="utf-8")
    return dest


def revision(rev, down, body, doc="test"):
    return f'"""{doc}"""\nfrom alembic import op\nimport sqlalchemy as sa\nrevision = "{rev}"\ndown_revision = "{down}"\nbranch_labels = None\ndepends_on = None\n\n\ndef upgrade():\n    {body}\n\n\ndef downgrade():\n    pass\n'


def deploy_backups(tmp_path):
    return (
        sorted(p.name for p in (tmp_path / "backups").glob("gabee_pg16_deploy_*.dump"))
        if (tmp_path / "backups").exists()
        else []
    )


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_full_deploy_success_with_existing_data(fake_shared, tmp_path):
    fs = fake_shared
    reset_db(fs)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = backups / "gabee_pg16.dump"
    old.write_bytes(b"manual backup that must stay untouched" * 100)
    old_hash, before = sha256(old), counts(fs)

    result = deployer(fs, tmp_path).run()

    assert result["outcome"] == "success", result["message"]
    assert revision_of(fs) == [HEAD]
    assert counts(fs) == before  # 기존 데이터 보존
    assert sha256(old) == old_hash  # 기존 백업 보존
    [dump] = deploy_backups(tmp_path)
    assert dump.endswith(f"_{PRIOR}-to-{HEAD}.dump")
    assert (backups / f"{dump}.sha256").read_text().split()[0] == sha256(backups / dump)
    steps = {e["step"]: e["status"] for e in result["events"]}
    assert (
        steps["backup-verify"]
        == steps["restore-verify"]
        == steps["rehearsal"]
        == steps["post-verify"]
        == "ok"
    )
    assert not (tmp_path / "state" / "HALT").exists()
    with conn(fs) as c:  # 잠금이 해제되었는지
        assert c.execute("SELECT pg_try_advisory_lock(%s)", (deploy.ADVISORY_LOCK_KEY,)).fetchone()[
            0
        ]
    leftovers = docker("ps", "-a", "--format", "{{.Names}}").stdout
    assert "gabee-deploy-rehearsal" not in leftovers
    # 6) 산출된 백업은 새 PostgreSQL 16 에 독립적으로 복원되고 적용 전(PRIOR) 상태·데이터와 같다
    restored = restore_into_fresh_pg16(backups / dump)
    assert restored == {"version": 16, "revision": PRIOR, "counts": before, "vector": "1"}
    # 4) 신규 스키마 위에서 '구 코드'(신규 컬럼을 모르는 INSERT)가 계속 동작한다 — 추가형 변경의 하위 호환
    with conn(fs) as c:
        c.execute(
            "INSERT INTO expenses (id, group_id, title, amount, date, category, paid_by, created_at) VALUES ('x1','g1','점심',9000,'2026-10-22','식비','u1',now())"
        )
        assert c.execute(
            "SELECT split_among::text, target_tag, settled_at FROM expenses WHERE id='x1'"
        ).fetchone() == ("[]", "all", None)


def test_already_latest_is_not_applied_again(fake_shared, tmp_path):
    reset_db(fake_shared, "head")
    result = deployer(fake_shared, tmp_path).run()
    assert result["outcome"] == "noop"
    assert deploy_backups(tmp_path) == []
    assert revision_of(fake_shared) == [HEAD]


def test_dry_run_backs_up_and_rehearses_but_does_not_apply(fake_shared, tmp_path):
    reset_db(fake_shared)
    result = deployer(fake_shared, tmp_path, dry_run=True).run()
    assert result["outcome"] == "dry_run_ok"
    assert revision_of(fake_shared) == [PRIOR]
    assert len(deploy_backups(tmp_path)) == 1


def test_backup_failure_aborts_without_touching_db(fake_shared, tmp_path):
    reset_db(fake_shared)
    not_a_dir = tmp_path / "backups"
    not_a_dir.write_text("파일이라 폴더를 만들 수 없음")
    result = deployer(fake_shared, tmp_path).run()
    assert result["outcome"] == "blocked"
    assert revision_of(fake_shared) == [PRIOR]
    assert not (tmp_path / "state" / "HALT").exists()


def test_corrupted_backup_aborts_before_apply(fake_shared, tmp_path):
    reset_db(fake_shared)
    hooks = {"after_backup": lambda path: Path(path).write_bytes(b"garbage" * 1000)}
    result = deployer(fake_shared, tmp_path, hooks=hooks).run()
    assert result["outcome"] == "blocked" and "무결성" in result["message"]
    assert revision_of(fake_shared) == [PRIOR]


def test_failed_restore_verification_aborts_before_apply(fake_shared, tmp_path):
    reset_db(fake_shared)
    # 무결성(목차)은 통과하지만 복원할 수 없는 덤프: 임시 컨테이너 이미지를 존재하지 않는 태그로 바꿔 복원 단계 실패를 재현
    result = deployer(fake_shared, tmp_path, hooks={"after_backup": lambda p: None}).run()
    assert result["outcome"] == "success"  # 대조군: 정상이면 성공
    reset_db(fake_shared)
    broken = deployer(fake_shared, tmp_path / "second")
    broken._rehearse = lambda *a, **k: (_ for _ in ()).throw(
        deploy.Failure("blocked", "백업 복원 검증에 실패했습니다: 시뮬레이션")
    )
    result = broken.run()
    assert result["outcome"] == "blocked" and "복원" in result["message"]
    assert revision_of(fake_shared) == [PRIOR]


def test_concurrent_deploy_is_prevented_by_advisory_lock(fake_shared, tmp_path):
    reset_db(fake_shared)
    with conn(fake_shared) as other:
        assert other.execute(
            "SELECT pg_try_advisory_lock(%s)", (deploy.ADVISORY_LOCK_KEY,)
        ).fetchone()[0]
        result = deployer(fake_shared, tmp_path).run()
    assert result["outcome"] == "blocked" and "advisory lock" in result["message"]
    assert revision_of(fake_shared) == [PRIOR]
    assert deploy_backups(tmp_path) == []


def test_destructive_and_conflicting_migrations_stop_before_backup(fake_shared, tmp_path):
    reset_db(fake_shared)
    head = HEAD
    drop = alembic_copy(
        tmp_path / "d", {"d1_drop.py": revision("d1", head, 'op.drop_column("users", "name")')}
    )
    result = deployer(fake_shared, tmp_path / "d", alembic_dir=drop).run()
    assert result["outcome"] == "blocked" and "drop_column" in result["message"]

    fork = alembic_copy(tmp_path / "f", {"f1_fork.py": revision("f1", "9e28d84c1686", "pass")})
    result = deployer(fake_shared, tmp_path / "f", alembic_dir=fork).run()
    assert result["outcome"] == "blocked" and "head" in result["message"]

    assert deploy_backups(tmp_path / "d") == deploy_backups(tmp_path / "f") == []
    assert revision_of(fake_shared) == [PRIOR]


def test_rehearsal_catches_data_conflict_and_protects_real_db(fake_shared, tmp_path):
    reset_db(fake_shared)
    # 기존 데이터(그룹 g1 에 멤버 2명)와 충돌하는 UNIQUE 제약: 빈 DB 에서는 통과하지만 실제 데이터 복사본에서는 실패해야 한다
    body = 'op.create_unique_constraint("uq_gm_group_demo", "group_members", ["group_id"])\n    op.execute("SELECT 1")'
    conflict = revision("e1", HEAD, body)
    result = deployer(
        fake_shared, tmp_path, alembic_dir=alembic_copy(tmp_path, {"e1_conflict.py": conflict})
    ).run()
    assert result["outcome"] == "blocked" and "리허설" in result["message"]
    assert revision_of(fake_shared) == [PRIOR]  # 실제 DB 미변경
    assert not (tmp_path / "state" / "HALT").exists()


def test_apply_failure_halts_then_retry_policy(fake_shared, tmp_path):
    reset_db(fake_shared)
    # 리허설 DB(gabee_rehearsal)에서는 통과하고 실제 DB(gabee)에서만 실패하는 리비전
    body = "op.execute(\"DO $$ BEGIN IF current_database() = 'gabee' THEN RAISE EXCEPTION 'boom'; END IF; END $$\")"
    bad = alembic_copy(tmp_path / "bad", {"g1_boom.py": revision("g1", HEAD, body)})
    first = deployer(fake_shared, tmp_path, alembic_dir=bad).run()
    assert first["outcome"] == "failed" and "변경되지 않았음" in first["message"]
    assert revision_of(fake_shared) == [
        PRIOR
    ]  # 전체가 한 트랜잭션이라 롤백됨(자동 롤백 코드는 없음)
    assert (tmp_path / "state" / "HALT").exists()
    assert len(deploy_backups(tmp_path)) == 1

    again = deployer(fake_shared, tmp_path, alembic_dir=bad).run()
    assert again["outcome"] == "halted"  # 재시도 정책: 사람이 HALT 를 지울 때까지 중단
    assert len(deploy_backups(tmp_path)) == 1

    (tmp_path / "state" / "HALT").unlink()
    fixed = deployer(fake_shared, tmp_path).run()  # 원인(잘못된 리비전)을 제거한 뒤 재실행
    assert fixed["outcome"] == "success"
    assert revision_of(fake_shared) == [HEAD]


def test_post_apply_privilege_audit_detects_app_without_grants(fake_shared, tmp_path):
    reset_db(fake_shared)
    with psycopg.connect(dbname="gabee", **fake_shared["admin"]) as c:
        c.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE gabee_migrator IN SCHEMA public REVOKE ALL ON TABLES FROM gabee_app"
        )
    result = deployer(fake_shared, tmp_path).run()
    assert result["outcome"] == "failed" and "gabee_app" in result["message"]
    assert (tmp_path / "state" / "HALT").exists()


def test_ci_failure_never_reaches_the_database(fake_shared, tmp_path):
    reset_db(fake_shared)
    ci = FakeCi()
    ci.status = "not_green"
    result = deployer(fake_shared, tmp_path, ci=ci).run()
    assert result["outcome"] == "blocked"
    assert revision_of(fake_shared) == [PRIOR] and deploy_backups(tmp_path) == []


def test_revision_files_changed_after_rehearsal_are_not_applied(fake_shared, tmp_path):
    reset_db(fake_shared)
    ad = alembic_copy(tmp_path, {})
    target = ad / "versions" / "6304cb91e46a_billing_settled_and_manager.py"
    suffix = chr(10) + "# 리허설 뒤 수정" + chr(10)
    hooks = {
        "before_apply": lambda: target.write_text(
            target.read_text(encoding="utf-8") + suffix, encoding="utf-8"
        )
    }
    result = deployer(fake_shared, tmp_path, alembic_dir=ad, hooks=hooks).run()
    assert result["outcome"] == "blocked" and "리허설 이후" in result["message"]
    assert revision_of(fake_shared) == [PRIOR] and not (tmp_path / "state" / "HALT").exists()


def test_rehearsed_and_applied_revisions_are_identical(fake_shared, tmp_path):
    reset_db(fake_shared)
    result = deployer(fake_shared, tmp_path).run()
    steps = {e["step"]: e for e in result["events"]}
    assert result["outcome"] == "success"
    assert steps["revision-identity"]["status"] == "ok"
    assert (
        f"{PRIOR} → {HEAD}" in steps["rehearsal"]["detail"]
        and f"{PRIOR} → {HEAD}" in steps["apply"]["detail"] + steps["revision-identity"]["detail"]
    )
    assert revision_of(fake_shared) == [HEAD]


def test_two_simultaneous_deploys_only_one_runs(fake_shared, tmp_path):
    reset_db(fake_shared)
    reached, release = threading.Event(), threading.Event()

    def hold():
        reached.set()
        assert release.wait(180)

    first = deployer(fake_shared, tmp_path / "a", hooks={"before_apply": hold})
    results = {}
    thread = threading.Thread(target=lambda: results.update(first=first.run()))
    thread.start()
    try:
        assert reached.wait(240), "첫 배포가 적용 직전에 도달하지 못함"
        second = deployer(fake_shared, tmp_path / "b").run()  # 첫 배포가 잠금을 쥔 채 대기 중
    finally:
        release.set()
        thread.join(240)
    assert second["outcome"] == "blocked" and "advisory lock" in second["message"]
    assert deploy_backups(tmp_path / "b") == []
    assert results["first"]["outcome"] == "success" and revision_of(fake_shared) == [HEAD]


@pytest.fixture
def api_on_fake_pg(fake_shared, monkeypatch):
    """실제 FastAPI 앱을 가짜 공용 DB(PostgreSQL 16)에 붙여 서버를 시작한다."""
    url = f"postgresql+psycopg://gabee_migrator:{fake_shared['migrator_pw']}@127.0.0.1:{fake_shared['port']}/gabee"
    pg_engine = create_engine(url, connect_args={"connect_timeout": 5}, pool_pre_ping=True)
    original = app_db.engine
    monkeypatch.setattr(app_db, "engine", pg_engine)
    app_db.SessionLocal.configure(bind=pg_engine)
    for name in (
        "schema_recheck_ready_seconds",
        "schema_recheck_not_ready_seconds",
        "schema_force_min_interval_seconds",
    ):
        monkeypatch.setattr(settings, name, 0)
    monitor.reset()
    try:
        with TestClient(
            app
        ) as client:  # lifespan(init_db) 이 DB 가 뒤처져 있어도 실패하지 않아야 한다
            yield client
    finally:
        app_db.SessionLocal.configure(bind=original)
        monitor.reset()
        pg_engine.dispose()


HEADERS = {"X-Gyeot-Token": "t1"}  # reset_db 가 만든 가족 그룹(g1)의 사용자


def api_state(client):
    """(기존 구조만 쓰는 API 상태코드들, 가계 API 상태코드)"""
    paths = (
        "/family-group/me",
        "/schedule/events",
        "/care/location/consent",
        "/family-chat/messages",
    )
    existing = [client.get(path, headers=HEADERS).status_code for path in paths]
    return existing, client.get("/billing/expenses", headers=HEADERS).status_code


def test_app_stays_up_while_shared_db_is_behind_and_opens_after_auto_deploy(
    fake_shared, tmp_path, api_on_fake_pg
):
    """공용 DB 자동 배포 도중의 일시적 불일치: 서버는 계속 동작하고, 새 스키마가 필요한 기능은 503 이다가
    배포가 끝나면 서버 재시작 없이 열린다. (대기 중인 마이그레이션이 users 컬럼을 추가하므로 가입·로그인 쪽이
    준비되지 않아 모든 기능이 막힌다 — 이 코드는 어차피 users 를 읽을 수 없다.)"""
    client = api_on_fake_pg
    reset_db(fake_shared)  # 서버가 뜬 뒤 DB 를 코드보다 뒤처진 상태(PRIOR)로 만든다
    observed = {}

    def during_deploy():  # 리허설을 마치고 적용 직전: 아직 DB 는 뒤처져 있다
        observed["state"] = api_state(client)
        observed["health"] = client.get("/health/db").json()

    behind = client.get("/health/db")
    report = behind.json()
    assert report["status"] == "degraded" and report["revision_state"] == "behind"
    assert report["pending_revisions"] == pending_after(PRIOR) and report["db_connected"] is True
    assert report["features"]["billing"]["ready"] is False
    for leaked in (fake_shared["migrator_pw"], "gabee_migrator", "127.0.0.1"):
        assert leaked not in behind.text
    assert api_state(client) == ([503, 503, 503, 503], 503)
    assert client.get("/health").json() == {"status": "ok"}  # 서버 자체는 살아 있다

    result = deployer(fake_shared, tmp_path, hooks={"before_apply": during_deploy}).run()

    assert result["outcome"] == "success", result["message"]
    assert observed["state"] == ([503, 503, 503, 503], 503)  # 배포 도중에도 동일
    assert observed["health"]["revision_state"] == "behind"
    assert api_state(client) == ([200, 200, 200, 200], 200)  # 서버 재시작 없이 열림
    ready = client.get("/health/db").json()
    assert ready["status"] == "ready" and ready["db_revision"] == ready["code_head"] == HEAD
    assert ready["pending_revisions"] == [] and ready["schema_ready"] is True


def test_failed_auto_deploy_leaves_server_degraded_but_running(
    fake_shared, tmp_path, api_on_fake_pg
):
    client = api_on_fake_pg
    reset_db(fake_shared)
    body = "op.execute(\"DO $$ BEGIN IF current_database() = 'gabee' THEN RAISE EXCEPTION 'boom'; END IF; END $$\")"
    bad = alembic_copy(tmp_path / "bad", {"g1_boom.py": revision("g1", HEAD, body)})
    result = deployer(fake_shared, tmp_path, alembic_dir=bad).run()
    assert result["outcome"] == "failed"
    assert api_state(client) == (
        [503, 503, 503, 503],
        503,
    )  # 실패한 배포는 DB 를 바꾸지 않음 → 계속 막혀 있음
    assert client.get("/health").json() == {"status": "ok"}
    report = client.get("/health/db").json()
    assert report["revision_state"] == "behind" and report["db_revision"] == PRIOR
