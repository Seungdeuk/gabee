"""팀 공용 PostgreSQL(192.168.0.44:5432/gabee)에 Alembic 마이그레이션을 자동 적용한다.

.github/workflows/deploy-shared-db.yml 이 self-hosted 러너에서 호출한다. 설계와 보안 모델은
docs/adr/0006-shared-db-auto-migration.md 참고. 핵심 원칙:

- CI 가 통과한 main 최신 커밋만 배포한다. CI 확인은 GitHub API 로만 하고, 이를 건너뛰는 옵션은 없다.
- 접속 대상은 SHARED(코드에 고정)와 정확히 같아야 한다. 환경변수·URL 로 바꿀 수 없다.
- 새 백업을 만들고, 무결성을 확인하고, 임시 PostgreSQL 16 에 복원해 검증하고, 그 복사본에
  마이그레이션을 먼저 적용해 본(리허설) 뒤에만 실제 DB 에 적용한다.
- 안전 검사에 하나라도 실패하면 DB 를 건드리지 않고 중단한다. 자동 롤백은 하지 않는다.
- DB 비밀번호는 pgpass 파일로만 전달한다(명령줄·환경변수·URL·로그에 나오지 않음).

사용법(러너에서): python scripts/shared_db_deploy.py run --sha <커밋> --repo <owner/repo> \
    --backup-dir <경로> --state-dir <경로> --pgpass <경로> [--dry-run] [--result-file <경로>]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import migration_risk  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
BACKUP_PREFIX = "gabee_pg16_deploy_"
BACKUP_NAME_RE = re.compile(r"^gabee_pg16_deploy_\d{8}T\d{6}Z_[0-9a-f]+-to-[0-9a-f]+\.dump$")
ADVISORY_LOCK_KEY = 727_005_001  # 공용 DB 마이그레이션 전용 잠금 키
REQUIRED_PG_MAJOR = 16
PG_IMAGE = "pgvector/pgvector:pg16"
CI_WORKFLOW_PATH = ".github/workflows/ci-check.yml"
CI_REQUIRED_JOBS = ("api", "api-postgres", "mobile")

# 서버 쪽 lock_timeout 으로 개발자 서버를 오래 막지 않고, 오래 걸리면 실패시킨다.
PGOPTIONS = "-c lock_timeout=10000 -c statement_timeout=300000 -c idle_in_transaction_session_timeout=300000"


@dataclasses.dataclass(frozen=True)
class Target:
    host: str
    port: int
    database: str
    user: str
    tools_host: str | None = None  # Docker 안의 pg_dump 가 접속할 주소(기본: host)
    tools_port: int | None = None
    docker_network: str | None = None


SHARED = Target("192.168.0.44", 5432, "gabee", "gabee_migrator")
FORBIDDEN_DATABASES = {"family-secretary", "postgres", "template0", "template1"}
FORBIDDEN_USERS = {"gabee_app", "postgres"}


class Refused(Exception):
    """잘못된 대상·사용법. DB 에 연결하기 전에 거부한다(종료 코드 2)."""


@dataclasses.dataclass
class CiVerdict:
    status: str  # ok | not_green | stale | unknown
    reason: str = ""


class GitHubCiVerifier:
    """GitHub API 로 '이 커밋의 CI Check 가 main push 에서 모든 필수 Job 성공'인지 확인한다."""

    def __init__(self, repo: str, token: str, fetch: Callable[[str], dict] | None = None) -> None:
        self.repo, self._token = repo, token
        self._fetch = fetch or self._http_get

    def _http_get(self, path: str) -> dict:
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.load(resp)

    def verify(self, sha: str) -> CiVerdict:
        try:
            tip = self._fetch(f"/repos/{self.repo}/branches/main")["commit"]["sha"]
            if tip != sha:
                return CiVerdict(
                    "stale", f"main 최신 커밋이 {tip[:8]} 로 바뀌었습니다(배포 대상 {sha[:8]})"
                )
            runs = self._fetch(
                f"/repos/{self.repo}/actions/runs?head_sha={sha}&event=push&branch=main&per_page=30"
            ).get("workflow_runs", [])
            candidates = [
                r
                for r in runs
                if r.get("path", "").startswith(CI_WORKFLOW_PATH)
                and r.get("head_sha") == sha
                and r.get("head_branch") == "main"
                and r.get("event") == "push"
                and r.get("status") == "completed"
                and (r.get("head_repository") or {}).get("full_name") == self.repo
            ]
            if not candidates:
                return CiVerdict(
                    "not_green", "이 커밋의 완료된 CI Check(push, main) 실행을 찾을 수 없습니다"
                )
            run = max(candidates, key=lambda r: r.get("run_number", 0))
            if run.get("conclusion") != "success":
                return CiVerdict("not_green", f"CI Check 결론이 {run.get('conclusion')} 입니다")
            jobs = self._fetch(f"/repos/{self.repo}/actions/runs/{run['id']}/jobs?per_page=100")
            results = {j["name"]: j.get("conclusion") for j in jobs.get("jobs", [])}
            bad = [n for n in CI_REQUIRED_JOBS if results.get(n) != "success"]
            if bad:
                return CiVerdict("not_green", f"필수 Job 이 성공하지 않았습니다: {bad}")
            return CiVerdict("ok", f"CI Check run {run['id']} 성공")
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
            return CiVerdict("unknown", f"CI 상태를 확인할 수 없습니다: {type(exc).__name__}")


class Failure(Exception):
    def __init__(self, outcome: str, message: str, *, halt: bool = False) -> None:
        super().__init__(message)
        self.outcome, self.message, self.halt = outcome, message, halt


class Deployer:
    def __init__(
        self,
        *,
        target: Target,
        trusted_targets: tuple[Target, ...],
        sha: str,
        backup_dir: Path,
        state_dir: Path,
        pgpass: Path,
        ci_verifier,
        dry_run: bool = False,
        alembic_dir: Path | None = None,
        api_root: Path = API_ROOT,
        retention: int = 14,
        verify_checkout: bool = True,
        image: str = PG_IMAGE,
        hooks: dict[str, Callable] | None = None,
    ) -> None:
        self.target, self.trusted = target, trusted_targets
        self.sha, self.dry_run, self.retention = sha, dry_run, retention
        self.backup_dir, self.state_dir, self.pgpass = (
            Path(backup_dir),
            Path(state_dir),
            Path(pgpass),
        )
        self.ci, self.api_root, self.image = ci_verifier, Path(api_root), image
        self.alembic_dir = Path(alembic_dir) if alembic_dir else self.api_root / "alembic"
        self.verify_checkout, self.hooks = verify_checkout, hooks or {}
        self.events: list[dict] = []
        self.result: dict = {"outcome": "failed", "sha": sha}
        self._lock_conn: psycopg.Connection | None = None
        self._containers: list[str] = []

    # ---------- 기록 ----------
    def log(self, step: str, status: str, detail: str = "") -> None:
        event = {
            "ts": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "step": step,
            "status": status,
            "detail": detail,
        }
        self.events.append(event)
        print(f"[{status}] {step}" + (f" — {detail}" if detail else ""), flush=True)

    def _hook(self, name: str, *args) -> None:
        if name in self.hooks:
            self.hooks[name](*args)

    # ---------- 대상 검증 ----------
    def validate_target(self) -> None:
        t = self.target
        if t not in self.trusted:
            raise Refused(f"허용된 배포 대상이 아닙니다: {t.host}:{t.port}/{t.database} ({t.user})")
        if t.database in FORBIDDEN_DATABASES:
            raise Refused(f"접근이 금지된 DB 입니다: {t.database}")
        if t.user in FORBIDDEN_USERS:
            raise Refused(f"DDL 에 쓸 수 없는 계정입니다: {t.user} (gabee_migrator 전용)")
        if not self.pgpass.is_file():
            raise Refused("pgpass 파일을 찾을 수 없습니다")

    def _connect(self) -> psycopg.Connection:
        t = self.target
        return psycopg.connect(
            host=t.host,
            port=t.port,
            dbname=t.database,
            user=t.user,
            passfile=str(self.pgpass),
            connect_timeout=10,
            autocommit=True,
            application_name="gabee-auto-migrate",
            options=PGOPTIONS,
        )

    def _verify_connected_server(self, conn: psycopg.Connection) -> None:
        db, user, version, is_super = conn.execute(
            "SELECT current_database(), current_user, current_setting('server_version_num')::int,"
            " (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
        ).fetchone()
        if (db, user) != (self.target.database, self.target.user):
            raise Failure("blocked", f"접속된 서버가 대상과 다릅니다: database={db} user={user}")
        if is_super:
            raise Failure("blocked", "슈퍼유저 계정으로는 자동 배포하지 않습니다")
        if version // 10000 != REQUIRED_PG_MAJOR:
            raise Failure("blocked", f"PostgreSQL {REQUIRED_PG_MAJOR} 서버가 아닙니다: {version}")

    # ---------- Alembic 분석 ----------
    def _script(self) -> ScriptDirectory:
        cfg = Config()
        cfg.set_main_option("script_location", str(self.alembic_dir))
        return ScriptDirectory.from_config(cfg)

    def _analyze(self, script: ScriptDirectory, current: str):
        heads = script.get_heads()
        if len(heads) != 1:
            raise Failure("blocked", f"Alembic head 가 {len(heads)}개입니다: {sorted(heads)}")
        head = heads[0]
        try:
            script.get_revision(current)
        except Exception as exc:  # alembic.util.CommandError 등
            raise Failure(
                "blocked",
                f"DB 리비전 {current} 이(가) 코드 이력에 없습니다(DB 가 앞서 있거나 갈라짐)",
            ) from exc
        if current == head:
            return head, []
        pending = [r for r in script.iterate_revisions(head, current) if r.revision != current]
        return head, pending[::-1]

    def _risk_scan(self, pending) -> None:
        findings = []
        for rev in pending:
            findings += migration_risk.scan_file(Path(rev.path), rev.revision)
        for f in findings:
            self.log("risk-scan", f.severity, str(f))
        blocked = migration_risk.blocking(findings)
        if blocked:
            raise Failure(
                "blocked",
                "파괴적·트랜잭션 밖 변경이 있어 자동 적용하지 않습니다: "
                + "; ".join(f"{f.revision}:{f.code}" for f in blocked),
            )

    # ---------- 서브프로세스 ----------
    def _env(self, url: str, passfile: Path | None = None) -> dict[str, str]:
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "DATABASE_URL"
        }
        env.update(
            {
                "DATABASE_URL": url,
                "PGOPTIONS": PGOPTIONS,
                "PGCONNECT_TIMEOUT": "10",
                "PGAPPNAME": "gabee-auto-migrate",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        if passfile:
            env["PGPASSFILE"] = str(passfile)
        return env

    def _run(
        self,
        cmd: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def _py(self, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
        return self._run([sys.executable, *args], env=env, cwd=self.api_root)

    def _alembic_upgrade(self, env: dict[str, str]) -> subprocess.CompletedProcess:
        """배포기가 분석·검사한 바로 그 리비전 폴더(self.alembic_dir)로 upgrade head 를 실행한다
        (alembic.ini 의 고정 경로에 의존하지 않는다). 로그에 'Running upgrade A -> B' 가 남는다."""
        code = "\n".join(
            [
                "import logging, sys",
                "from alembic import command",
                "from alembic.config import Config",
                "logging.basicConfig(level=logging.INFO, format='%(levelname)-5s [%(name)s] %(message)s')",
                "cfg = Config()",
                "cfg.set_main_option('script_location', sys.argv[1])",
                "command.upgrade(cfg, 'head')",
            ]
        )
        return self._py(["-c", code, str(self.alembic_dir)], env)

    def _shared_url(self) -> str:
        t = self.target
        return f"postgresql+psycopg://{t.user}@{t.host}:{t.port}/{t.database}"

    # ---------- 백업 ----------
    def _docker_mount(self, path: Path) -> str:
        return str(path).replace("\\", "/")

    def _backup(self, from_rev: str, to_rev: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        need = max(
            500 * 1024 * 1024,
            3 * max([p.stat().st_size for p in self.backup_dir.glob("*.dump")] or [0]),
        )
        free = shutil.disk_usage(self.backup_dir).free
        if free < need:
            raise Failure(
                "blocked",
                f"백업 폴더의 여유 공간이 부족합니다({free // 2**20}MB < {need // 2**20}MB)",
            )
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"{BACKUP_PREFIX}{stamp}_{from_rev}-to-{to_rev}.dump"
        final, partial = self.backup_dir / name, self.backup_dir / f"{name}.partial"
        t = self.target
        cmd = ["docker", "run", "--rm"]
        if t.docker_network:
            cmd += ["--network", t.docker_network]
        cmd += [
            "-v",
            f"{self._docker_mount(self.pgpass)}:/run/pgpass.src:ro",
            "-v",
            f"{self._docker_mount(self.backup_dir)}:/backup",
            "-e",
            "PGPASSFILE=/tmp/pgpass",
            "-e",
            "PGCONNECT_TIMEOUT=10",
            "--entrypoint",
            "sh",
            self.image,
            "-c",
            "cp /run/pgpass.src /tmp/pgpass && chmod 600 /tmp/pgpass && exec pg_dump --no-password "
            '--host "$0" --port "$1" --username "$2" --dbname "$3" --format=custom --file "$4"',
            t.tools_host or t.host,
            str(t.tools_port or t.port),
            t.user,
            t.database,
            f"/backup/{partial.name}",
        ]
        proc = self._run(cmd, timeout=1800)
        if proc.returncode != 0 or not partial.is_file():
            partial.unlink(missing_ok=True)
            raise Failure("blocked", f"백업(pg_dump)에 실패했습니다: {proc.stderr.strip()[-300:]}")
        partial.replace(final)
        self._protect_file(final)
        return final

    def _protect_file(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                user = os.environ.get("USERNAME", "")
                r = subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                    capture_output=True,
                    text=True,
                )
                self.log(
                    "backup-acl",
                    "ok" if r.returncode == 0 else "warn",
                    "소유자 전용 권한 적용" if r.returncode == 0 else r.stderr.strip()[:120],
                )
            else:
                path.chmod(0o600)
        except OSError as exc:
            self.log("backup-acl", "warn", str(exc))

    def _verify_backup(self, dump: Path) -> str:
        size = dump.stat().st_size
        if size < 1024:
            raise Failure("blocked", f"백업 파일이 비정상적으로 작습니다({size} bytes)")
        digest = hashlib.sha256(dump.read_bytes()).hexdigest()
        Path(f"{dump}.sha256").write_text(f"{digest}  {dump.name}\n", encoding="utf-8")
        proc = self._run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self._docker_mount(dump.parent)}:/backup:ro",
                "--entrypoint",
                "pg_restore",
                self.image,
                "--list",
                f"/backup/{dump.name}",
            ]
        )
        toc = proc.stdout
        if proc.returncode != 0 or "alembic_version" not in toc:
            raise Failure("blocked", "백업 무결성 확인(pg_restore --list)에 실패했습니다")
        if hashlib.sha256(dump.read_bytes()).hexdigest() != digest:
            raise Failure("blocked", "백업 파일이 확인 중 변경되었습니다")
        self.log("backup-verify", "ok", f"{dump.name} {size} bytes sha256={digest[:12]}")
        return digest

    # ---------- 복원 검증 + 리허설 ----------
    def _docker(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return self._run(["docker", *args], **kw)

    def _rehearse(self, dump: Path, conn: psycopg.Connection, current: str, head: str) -> None:
        name = f"gabee-deploy-rehearsal-{secrets.token_hex(4)}"
        password = secrets.token_urlsafe(24)
        env = {**os.environ, "POSTGRES_PASSWORD": password}  # 값은 환경으로 전달(명령줄에 없음)
        proc = self._docker(
            [
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "-e",
                "POSTGRES_PASSWORD",
                "-e",
                "POSTGRES_USER=gabee_rehearsal",
                "-e",
                "POSTGRES_DB=gabee_rehearsal",
                "-p",
                "127.0.0.1::5432",
                self.image,
            ],
            env=env,
        )
        if proc.returncode != 0:
            raise Failure(
                "blocked",
                f"임시 PostgreSQL 컨테이너를 시작하지 못했습니다: {proc.stderr.strip()[-200:]}",
            )
        self._containers.append(name)
        try:
            for _ in range(60):
                if (
                    self._docker(
                        [
                            "exec",
                            name,
                            "pg_isready",
                            "-U",
                            "gabee_rehearsal",
                            "-d",
                            "gabee_rehearsal",
                        ]
                    ).returncode
                    == 0
                ):
                    break
                time.sleep(1)
            else:
                raise Failure("blocked", "임시 PostgreSQL 이 준비되지 않았습니다")
            time.sleep(1)
            port_line = self._docker(["port", name, "5432/tcp"]).stdout.strip().splitlines()[0]
            port = int(port_line.rsplit(":", 1)[1])
            if self._docker(["cp", str(dump), f"{name}:/tmp/restore.dump"]).returncode != 0:
                raise Failure("blocked", "백업을 임시 컨테이너로 복사하지 못했습니다")
            restore = self._docker(
                [
                    "exec",
                    name,
                    "pg_restore",
                    "-U",
                    "gabee_rehearsal",
                    "-d",
                    "gabee_rehearsal",
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "/tmp/restore.dump",
                ]
            )
            if restore.returncode != 0:
                raise Failure(
                    "blocked", f"백업 복원 검증에 실패했습니다: {restore.stderr.strip()[-300:]}"
                )
            url = (
                f"postgresql+psycopg://gabee_rehearsal:{password}@127.0.0.1:{port}/gabee_rehearsal"
            )
            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                dbname="gabee_rehearsal",
                user="gabee_rehearsal",
                password=password,
                autocommit=True,
            ) as replica:
                restored_rev = replica.execute("SELECT version_num FROM alembic_version").fetchall()
                src_tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                    ).fetchall()
                }
                dst_tables = {
                    r[0]
                    for r in replica.execute(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                    ).fetchall()
                }
            if restored_rev != [(current,)] or src_tables != dst_tables:
                raise Failure(
                    "blocked",
                    f"복원본이 원본과 다릅니다(리비전 {restored_rev}, 테이블 차이 {sorted(src_tables ^ dst_tables)})",
                )
            self.log(
                "restore-verify",
                "ok",
                f"임시 DB 복원 확인(테이블 {len(dst_tables)}개, 리비전 {current})",
            )
            env2 = self._env(url)
            up = self._alembic_upgrade(env2)
            if up.returncode != 0:
                raise Failure(
                    "blocked",
                    f"실제 데이터 복사본에 대한 리허설 마이그레이션이 실패했습니다: {self._tail(up)}",
                )
            for check in (["scripts/check_schema_matches_models.py"],):
                res = self._py(check, env2)
                if res.returncode != 0:
                    raise Failure(
                        "blocked", f"리허설 후 스키마가 모델과 다릅니다: {self._tail(res)}"
                    )
            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                dbname="gabee_rehearsal",
                user="gabee_rehearsal",
                password=password,
                autocommit=True,
            ) as replica:
                if replica.execute("SELECT version_num FROM alembic_version").fetchall() != [
                    (head,)
                ]:
                    raise Failure("blocked", "리허설 후 리비전이 head 가 아닙니다")
            self.log("rehearsal", "ok", f"복사본에 {current} → {head} 적용 성공, 모델 일치")
        finally:
            self._docker(["rm", "-f", name])
            if name in self._containers:
                self._containers.remove(name)

    @staticmethod
    def _tail(proc: subprocess.CompletedProcess) -> str:
        text = (proc.stderr or proc.stdout or "").strip().splitlines()
        lines = [ln for ln in text if "Running upgrade" in ln or "Error" in ln or "error" in ln][
            -4:
        ] or text[-4:]
        return " | ".join(lines)[-400:]

    # ---------- 적용 및 사후 검증 ----------
    def _current_revisions(self) -> list[str] | None:
        try:
            with self._connect() as c:
                return [
                    r[0] for r in c.execute("SELECT version_num FROM alembic_version").fetchall()
                ]
        except psycopg.Error:
            return None

    def _revision_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted((self.alembic_dir / "versions").glob("*.py")):
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _assert_same_as_rehearsed(
        self,
        conn: psycopg.Connection,
        current: str,
        head: str,
        plan_ids: list[str],
        fingerprint: str,
    ) -> None:
        """리허설에서 검증한 것과 실제로 적용할 것이 같은지 적용 직전에 다시 확인한다:
        리비전 파일 해시, 적용 예정 리비전 목록·head, 그리고 DB 의 현재 리비전."""
        if self._revision_fingerprint() != fingerprint:
            raise Failure("blocked", "리허설 이후 리비전 파일이 바뀌어 적용하지 않습니다")
        new_head, pending = self._analyze(self._script(), current)
        if new_head != head or [r.revision for r in pending] != plan_ids:
            raise Failure("blocked", "리허설 이후 적용 예정 리비전이 바뀌어 적용하지 않습니다")
        rows = [r[0] for r in conn.execute("SELECT version_num FROM alembic_version").fetchall()]
        if rows != [current]:
            raise Failure(
                "blocked", f"리허설 이후 DB 리비전이 {current} 에서 {rows} 로 바뀌었습니다"
            )
        self.log(
            "revision-identity",
            "ok",
            f"리허설과 동일: {current} → {head} {plan_ids}, 파일 해시 {fingerprint[:12]}",
        )

    def _apply(self, current: str, head: str) -> None:
        self.log("apply", "start", f"{current} → {head} (gabee_migrator)")
        env = self._env(self._shared_url(), self.pgpass)
        proc = self._alembic_upgrade(env)
        if proc.returncode != 0:
            state = self._current_revisions()
            if state == [current]:
                detail = f"마이그레이션 실패, DB 는 변경되지 않았음을 확인했습니다(리비전 {current}): {self._tail(proc)}"
            elif state is None:
                detail = f"마이그레이션 중 연결이 끊겼고 현재 DB 상태를 확인할 수 없습니다: {self._tail(proc)}"
            else:
                detail = f"마이그레이션 실패, 예상 밖 리비전 {state}: {self._tail(proc)}"
            raise Failure("failed", detail, halt=True)
        self.log("apply", "ok")

    def _post_verify(self, head: str) -> None:
        state = self._current_revisions()
        if state != [head]:
            raise Failure("failed", f"적용 후 리비전이 head 가 아닙니다: {state}", halt=True)
        res = self._py(
            ["scripts/check_schema_matches_models.py"], self._env(self._shared_url(), self.pgpass)
        )
        if res.returncode != 0:
            raise Failure(
                "failed", f"적용 후 스키마가 모델과 다릅니다: {self._tail(res)}", halt=True
            )
        problems = self._app_privilege_problems()
        if problems:
            raise Failure(
                "failed",
                "gabee_app 권한 점검 실패(신규 객체에 앱 권한이 없거나 DDL 권한이 있음): "
                + "; ".join(problems[:6]),
                halt=True,
            )
        self.log("post-verify", "ok", f"리비전 {head}, 모델 일치, gabee_app 권한 정상")

    def _app_privilege_problems(self) -> list[str]:
        problems: list[str] = []
        with self._connect() as c:
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='gabee_app'").fetchone():
                return ["gabee_app 역할이 없습니다"]
            if c.execute("SELECT has_schema_privilege('gabee_app','public','CREATE')").fetchone()[
                0
            ]:
                problems.append("gabee_app 이 public 스키마에 CREATE(DDL) 권한을 가짐")
            if c.execute("SELECT rolsuper FROM pg_roles WHERE rolname='gabee_app'").fetchone()[0]:
                problems.append("gabee_app 이 슈퍼유저임")
            for (table,) in c.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'"
            ).fetchall():
                ok = c.execute(
                    "SELECT has_table_privilege('gabee_app', %s, 'SELECT,INSERT,UPDATE,DELETE')",
                    (f"public.{table}",),
                ).fetchone()[0]
                if not ok:
                    problems.append(f"테이블 {table} 에 gabee_app CRUD 권한 없음")
            for (seq,) in c.execute(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='S'"
            ).fetchall():
                if not c.execute(
                    "SELECT has_sequence_privilege('gabee_app', %s, 'USAGE,SELECT,UPDATE')",
                    (f"public.{seq}",),
                ).fetchone()[0]:
                    problems.append(f"시퀀스 {seq} 에 gabee_app 권한 없음")
        return problems

    # ---------- 보관 정책 ----------
    def _apply_retention(self, keep: Path) -> None:
        dumps = sorted(
            (p for p in self.backup_dir.iterdir() if BACKUP_NAME_RE.match(p.name)),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in dumps[self.retention :]:
            if old != keep:
                old.unlink(missing_ok=True)
                Path(f"{old}.sha256").unlink(missing_ok=True)
                self.log("retention", "ok", f"오래된 배포 백업 삭제: {old.name}")
        for stale in self.backup_dir.glob(f"{BACKUP_PREFIX}*.partial"):
            if time.time() - stale.stat().st_mtime > 86400:
                stale.unlink(missing_ok=True)

    # ---------- 실행 ----------
    def _halt_path(self) -> Path:
        return self.state_dir / "HALT"

    def _checkout_ok(self) -> None:
        head = self._run(["git", "rev-parse", "HEAD"], cwd=self.api_root).stdout.strip()
        dirty = self._run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=self.api_root
        ).stdout.strip()
        if head != self.sha or dirty:
            raise Failure(
                "blocked",
                f"체크아웃이 검증된 커밋과 다릅니다(HEAD={head[:8]}, 대상={self.sha[:8]}, 변경={'있음' if dirty else '없음'})",
            )

    def run(self) -> dict:
        outcome, message = "failed", ""
        from_rev = to_rev = None
        backup: Path | None = None
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.validate_target()
            if self._halt_path().exists():
                raise Failure(
                    "halted",
                    f"이전 배포 실패로 중단 상태입니다(HALT): {self._halt_path().read_text(encoding='utf-8', errors='replace')[:200]}",
                )
            if self.verify_checkout:
                self._checkout_ok()
            verdict = self.ci.verify(self.sha)
            self.log("ci-verify", verdict.status, verdict.reason)
            if verdict.status == "stale":
                raise Failure("skipped", verdict.reason)
            if verdict.status != "ok":
                raise Failure(
                    "blocked", f"CI 검증을 통과하지 않아 배포하지 않습니다: {verdict.reason}"
                )

            script = self._script()
            conn = self._connect()
            self._lock_conn = conn
            self._verify_connected_server(conn)
            if not conn.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,)).fetchone()[
                0
            ]:
                raise Failure("blocked", "다른 마이그레이션이 실행 중입니다(advisory lock)")
            rows = (
                [r[0] for r in conn.execute("SELECT version_num FROM alembic_version").fetchall()]
                if conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0]
                else []
            )
            if len(rows) != 1:
                raise Failure("blocked", f"alembic_version 상태가 비정상입니다: {rows}")
            current = from_rev = rows[0]
            head, pending = self._analyze(script, current)
            to_rev = head
            if not pending:
                raise Failure("noop", f"이미 최신 리비전입니다({head})")
            self.log("plan", "ok", f"{current} → {head}, 적용 예정 {[r.revision for r in pending]}")
            self._risk_scan(pending)
            plan_ids = [r.revision for r in pending]
            fingerprint = self._revision_fingerprint()

            backup = self._backup(current, head)
            self.log("backup", "ok", backup.name)
            self._hook("after_backup", backup)
            self._verify_backup(backup)
            self._rehearse(backup, conn, current, head)

            verdict = self.ci.verify(self.sha)
            if verdict.status != "ok":
                raise Failure(
                    "skipped" if verdict.status == "stale" else "blocked",
                    f"적용 직전 재검증 실패: {verdict.reason}",
                )
            if self._halt_path().exists():
                raise Failure("halted", "적용 직전에 HALT 가 생겼습니다")
            if self.dry_run:
                outcome, message = (
                    "dry_run_ok",
                    "dry-run: 백업·복원·리허설까지 성공, 실제 DB 에는 적용하지 않음",
                )
            else:
                self._hook("before_apply")
                self._assert_same_as_rehearsed(conn, current, head, plan_ids, fingerprint)
                self._apply(current, head)
                self._post_verify(head)
                outcome, message = "success", f"{current} → {head} 적용 및 검증 완료"
            self._apply_retention(backup)
        except Failure as f:
            outcome, message = f.outcome, f.message
            if f.halt:
                self._write_halt(message)
        except Refused as r:
            outcome, message = "refused", str(r)
        except (psycopg.Error, OSError, subprocess.SubprocessError) as exc:
            outcome, message = (
                "blocked",
                f"예상하지 못한 오류로 중단했습니다({type(exc).__name__}): {str(exc)[:200]}",
            )
        finally:
            self._cleanup()
        level = "ok" if outcome in ("success", "noop", "skipped", "dry_run_ok") else "FAIL"
        self.log("result", level, f"{outcome}: {message}")
        self.result = {
            "outcome": outcome,
            "message": message,
            "sha": self.sha,
            "from": from_rev,
            "to": to_rev,
            "backup": backup.name if backup else None,
            "dry_run": self.dry_run,
            "events": self.events,
        }
        self._record()
        return self.result

    def _write_halt(self, message: str) -> None:
        self._halt_path().write_text(
            f"{dt.datetime.now(dt.UTC).isoformat()} sha={self.sha} {message}", encoding="utf-8"
        )
        self.log(
            "halt",
            "FAIL",
            "이후 배포를 중단합니다. 원인 해결 후 state-dir 의 HALT 파일을 삭제해야 재개됩니다",
        )

    def _cleanup(self) -> None:
        for name in list(self._containers):
            self._docker(["rm", "-f", name])
        if self._lock_conn is not None:
            try:
                self._lock_conn.close()
            except psycopg.Error:
                pass
            self._lock_conn = None

    def _record(self) -> None:
        try:
            with (self.state_dir / "deploy-log.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {k: v for k, v in self.result.items() if k != "events"}, ensure_ascii=False
                    )
                    + "\n"
                )
        except OSError:
            pass
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            lines = [
                f"## 공용 DB 자동 배포: {self.result['outcome']}",
                "",
                f"- 커밋: `{self.sha[:8]}`",
                f"- {self.result['message']}",
                f"- 리비전: `{self.result['from']}` → `{self.result['to']}`",
                f"- 백업: `{self.result['backup']}`",
                "",
                "| 단계 | 상태 | 내용 |",
                "|---|---|---|",
            ]
            lines += [
                f"| {e['step']} | {e['status']} | {e['detail'].replace('|', '/')} |"
                for e in self.events
            ]
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")


def notify(result: dict, repo: str, token: str, run_url: str, fetch=None) -> None:
    """팀원이 상태를 볼 수 있게 GitHub 이슈(`db-deploy-failed`)로 표시한다.
    blocked/failed 이면 이슈를 만들거나(열린 이슈가 있으면 댓글), success/noop 이면 열린 실패 이슈를 해결로 닫는다."""
    outcome = result.get("outcome")
    if outcome not in ("blocked", "failed", "success", "noop"):
        return
    api = fetch or _github_request
    open_issues = (
        api("GET", f"/repos/{repo}/issues?labels=db-deploy-failed&state=open&per_page=10", None)
        or []
    )
    if outcome in ("success", "noop"):
        for issue in open_issues:
            sha = str(result.get("sha"))[:8]
            body = "\n".join(
                [
                    f"해결됨: 배포 결과 `{outcome}` ({result.get('from')} → {result.get('to')}, 커밋 `{sha}`)",
                    run_url,
                ]
            )
            api("POST", f"/repos/{repo}/issues/{issue['number']}/comments", {"body": body})
            api("PATCH", f"/repos/{repo}/issues/{issue['number']}", {"state": "closed"})
        return
    body = "\n".join(
        [
            f"**결과**: {outcome}",
            "",
            result["message"],
            "",
            f"- 커밋: `{str(result.get('sha'))[:8]}`",
            f"- 리비전: `{result.get('from')}` → `{result.get('to')}`",
            f"- 백업: `{result.get('backup')}`",
            f"- 실행: {run_url}",
            "",
            "공용 DB 는 실패한 마이그레이션이 적용되지 않은 상태입니다(적용 중 실패는 전체 롤백). "
            "`failed` 이면 러너의 HALT 파일을 지우기 전까지 이후 배포가 멈춥니다.",
        ]
    )
    api(
        "POST",
        f"/repos/{repo}/labels",
        {"name": "db-deploy-failed", "color": "B60205"},
        ok_codes=(201, 422),
    )
    if open_issues:
        api("POST", f"/repos/{repo}/issues/{open_issues[0]['number']}/comments", {"body": body})
    else:
        api(
            "POST",
            f"/repos/{repo}/issues",
            {
                "title": f"공용 DB 자동 배포 실패 ({outcome})",
                "body": body,
                "labels": ["db-deploy-failed"],
            },
        )


def _github_request(
    method: str, path: str, payload: dict | None, ok_codes: tuple[int, ...] = (200, 201)
):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in ok_codes:
            return None
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--profile", choices=["shared"], default="shared")
    run.add_argument("--sha", required=True)
    run.add_argument("--repo", required=True)
    run.add_argument("--backup-dir", required=True, type=Path)
    run.add_argument("--state-dir", required=True, type=Path)
    run.add_argument("--pgpass", required=True, type=Path)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--result-file", type=Path)
    run.add_argument("--no-notify", action="store_true")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[REFUSED] GITHUB_TOKEN 이 없어 CI 통과 여부를 확인할 수 없습니다.")
        return 2
    deployer = Deployer(
        target=SHARED,
        trusted_targets=(SHARED,),
        sha=args.sha,
        backup_dir=args.backup_dir,
        state_dir=args.state_dir,
        pgpass=args.pgpass,
        ci_verifier=GitHubCiVerifier(args.repo, token),
        dry_run=args.dry_run,
    )
    result = deployer.run()
    if args.result_file:
        args.result_file.write_text(
            json.dumps({k: v for k, v in result.items() if k != "events"}, ensure_ascii=False),
            encoding="utf-8",
        )
    if not args.no_notify:
        server, run_id = (
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            os.environ.get("GITHUB_RUN_ID", ""),
        )
        try:
            notify(result, args.repo, token, f"{server}/{args.repo}/actions/runs/{run_id}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"[warn] 이슈 알림에 실패했습니다: {type(exc).__name__}")
    return {"refused": 2}.get(
        result["outcome"],
        0 if result["outcome"] in ("success", "noop", "skipped", "dry_run_ok") else 1,
    )


if __name__ == "__main__":
    sys.exit(main())
