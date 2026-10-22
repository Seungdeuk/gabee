"""공용 DB PC 에서 주기적으로(기본 5분) 실행되는 Pull Agent.

GitHub Self-hosted Runner 없이, 공용 DB PC 가 스스로 최신 main 을 확인해 마이그레이션을 반영한다.
배포 로직(CI 검증·위험 검사·백업·복원 리허설·적용·사후 검증·HALT·알림)은 `shared_db_deploy.py` 를
그대로 재사용하고, 이 파일은 다음만 한다:

1. 최신 main 커밋을 읽기 전용 토큰으로 확인하고, 이미 처리한 커밋이면 건너뛴다.
2. 그 정확한 커밋만 전용 클론에 체크아웃한다(PR·다른 브랜치 코드는 가져오지 않는다).
3. 배포 도구(이 파일, shared_db_deploy.py, migration_risk.py)와 alembic/env.py 등이 관리자가 검토(bless)한 것과
   다르면 자격증명으로 실행하지 않고 `held` 로 멈춘다 — 배포 기계 자체의 변경은 사람이 한 번 확인한다.
4. 오케스트레이터를 *고정된 복사본*(agent/ 폴더)으로 실행하고 결과를 상태 파일에 기록한다.

비밀(DB 비밀번호, GitHub 토큰)은 파일로만 받고 명령줄·로그에 쓰지 않는다. 설정은 agent.env(KEY=VALUE)와 환경변수.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shared_db_deploy as deploy  # noqa: E402  (같은 폴더의 고정된 복사본을 쓴다)

# 관리자가 검토해 agent/ 폴더에 고정해 둔 배포 도구. 체크아웃의 같은 파일과 다르면 held.
TOOL_FILES = (
    "apps/api/scripts/deploy_agent.py",
    "apps/api/scripts/shared_db_deploy.py",
    "apps/api/scripts/migration_risk.py",
)
# 체크아웃에서 실행되지만 DB 자격증명이 있는 프로세스에서 도는 파일. bless 때 해시를 기록해 두고 바뀌면 held.
TRUST_FILES = (
    "apps/api/alembic/env.py",
    "apps/api/alembic.ini",
    "apps/api/scripts/check_schema_matches_models.py",
)
# 자식 프로세스(git, 오케스트레이터)에 넘기는 환경변수. 그 밖의 변수(다른 비밀 포함)는 넘기지 않는다.
BASE_ENV_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
    "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT",
)  # fmt: skip
OK_OUTCOMES = {"disabled", "idle", "skipped", "success", "noop", "dry_run_ok"}
RETRY_BLOCKED_SECONDS = 30 * 60  # blocked(백업 실패 등)는 이 간격 이전에는 다시 시도하지 않는다


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"')
    return values


@dataclasses.dataclass
class Config:
    repo: str
    home: Path
    backup_dir: Path
    pgpass: Path
    token_file: Path
    git_url: str
    enabled: bool
    apply: bool
    python: str = sys.executable
    skip_pip: bool = False

    @classmethod
    def load(cls, env_file: Path | None = None, environ: dict[str, str] | None = None) -> Config:
        values = {
            **read_env_file(env_file or Path()),
            **(environ if environ is not None else os.environ),
        }
        try:
            home = Path(values["GABEE_DEPLOY_HOME"])
            backup_dir = Path(values["GABEE_BACKUP_DIR"])
            pgpass = Path(values["GABEE_PGPASS"])
        except KeyError as exc:
            raise deploy.Refused(f"필수 설정이 없습니다: {exc.args[0]}") from exc
        repo = values.get("GABEE_REPO", "kangminhun/gabee")
        flag = lambda name: values.get(name, "false").strip().lower() == "true"  # noqa: E731
        return cls(
            repo=repo,
            home=home,
            backup_dir=backup_dir,
            pgpass=pgpass,
            token_file=Path(values.get("GABEE_TOKEN_FILE", str(home / "secrets" / "github-token"))),
            git_url=values.get("GABEE_GIT_URL", f"https://github.com/{repo}.git"),
            enabled=flag("GABEE_AGENT_ENABLED"),
            apply=flag("GABEE_AGENT_APPLY"),
            python=values.get("GABEE_AGENT_PYTHON", sys.executable),
            skip_pip=flag("GABEE_AGENT_SKIP_PIP"),
        )


@contextmanager
def file_lock(path: Path) -> Iterator[bool]:
    """한 번에 하나의 에이전트만(작업 스케줄러가 겹쳐 실행해도). 잠금을 못 잡으면 False."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")  # noqa: SIM115
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            locked = False
        yield locked
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


class Agent:
    def __init__(self, cfg: Config, tools_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.tools_dir = tools_dir or Path(__file__).resolve().parent
        self.repo = cfg.home / "repo"
        self.state_dir = cfg.home / "state"
        self.logs_dir = cfg.home / "logs"

    # ---------- 기록 ----------
    def log(self, message: str) -> None:
        line = f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} {message}"
        print(line, flush=True)
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            with (self.logs_dir / f"agent-{dt.date.today():%Y-%m-%d}.log").open(
                "a", encoding="utf-8"
            ) as fh:
                fh.write(line + "\n")
            for old in sorted(self.logs_dir.glob("agent-*.log"))[:-30]:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    def _state_path(self) -> Path:
        return self.state_dir / "agent-state.json"

    def load_state(self) -> dict:
        try:
            return json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, **updates) -> dict:
        state = {**self.load_state(), **updates}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._state_path())
        return state

    def _finish(self, outcome: str, message: str, sha: str | None = None, **state) -> dict:
        self.log(f"[{outcome}] {message}" + (f" (커밋 {sha[:8]})" if sha else ""))
        return {"outcome": outcome, "message": message, "sha": sha, **state}

    # ---------- 신뢰 ----------
    def _trust_path(self) -> Path:
        return self.state_dir / "trust.json"

    def _load_trust(self) -> dict[str, str]:
        try:
            return json.loads(self._trust_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def trust_problems(self) -> list[str]:
        problems = []
        for rel in TOOL_FILES:
            fresh, pinned = self.repo / rel, self.tools_dir / Path(rel).name
            if not fresh.is_file():
                problems.append(f"{rel} 가 체크아웃에 없음")
            elif not pinned.is_file() or sha256_file(fresh) != sha256_file(pinned):
                problems.append(f"배포 도구가 바뀜: {Path(rel).name}")
        trust = self._load_trust()
        for rel in TRUST_FILES:
            fresh = self.repo / rel
            if rel not in trust:
                problems.append(f"검토(bless)되지 않음: {rel}")
            elif not fresh.is_file() or sha256_file(fresh) != trust[rel]:
                problems.append(f"배포 신뢰 파일이 바뀜: {rel}")
        return problems

    def bless(self, sha: str, token: str | None = None) -> list[str]:
        """관리자가 검토한 커밋의 배포 도구를 agent/ 에 고정하고 신뢰 파일 해시를 기록한다."""
        self._git_sync(sha, token)
        changed = []
        for rel in TOOL_FILES:
            src, dst = self.repo / rel, self.tools_dir / Path(rel).name
            if not dst.is_file() or sha256_file(src) != sha256_file(dst):
                changed.append(Path(rel).name)
                if src.resolve() != dst.resolve():
                    tmp = dst.with_suffix(dst.suffix + ".new")
                    shutil.copyfile(src, tmp)
                    tmp.replace(dst)
        trust = {rel: sha256_file(self.repo / rel) for rel in TRUST_FILES}
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._trust_path().write_text(json.dumps(trust, indent=2), encoding="utf-8")
        self.save_state(held_reason=None, blessed_sha=sha)
        return changed

    # ---------- git ----------
    def _git_env(self, token: str | None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k in BASE_ENV_KEYS}
        env["GIT_TERMINAL_PROMPT"] = "0"
        if token and self.cfg.git_url.startswith("https://github.com/"):
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update(  # 토큰은 환경변수로만 전달(명령줄·프로세스 목록에 나타나지 않음)
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}",
            )
        return env

    def _git(self, *args: str, token: str | None = None, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, env=self._git_env(token), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=600,
        )  # fmt: skip
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} 실패: {proc.stderr.strip()[-200:]}")
        return proc.stdout.strip()

    def _git_sync(self, sha: str, token: str | None = None) -> None:
        """main 을 가져와 정확히 sha 를 체크아웃한다(그 커밋이 main 이력에 없으면 실패)."""
        self.repo.mkdir(parents=True, exist_ok=True)
        if not (self.repo / ".git").exists():
            self._git("init", "-q", cwd=self.repo)
            self._git("remote", "add", "origin", self.cfg.git_url)
        self._git("fetch", "--no-tags", "--quiet", "--depth", "100", "origin", "main", token=token)
        self._git("cat-file", "-e", f"{sha}^{{commit}}")
        self._git("merge-base", "--is-ancestor", sha, "FETCH_HEAD")  # main 이력에 있는 커밋만
        self._git("checkout", "--detach", "--force", "--quiet", sha)
        self._git("clean", "-ffdxq")
        if self._git("rev-parse", "HEAD") != sha:
            raise RuntimeError("체크아웃이 대상 커밋과 다릅니다")

    # ---------- 실행 ----------
    def _should_skip(self, tip: str) -> str | None:
        state = self.load_state()
        if state.get("last_sha") != tip:
            return None
        outcome, mode = state.get("last_outcome"), state.get("last_mode")
        want_mode = "apply" if self.cfg.apply else "dry"
        if outcome in ("success", "noop"):
            return f"이미 처리한 커밋입니다({outcome})"
        if outcome == "dry_run_ok" and mode == want_mode:
            return "이미 dry-run 으로 처리한 커밋입니다"
        if outcome == "blocked" and time.time() < state.get("retry_after", 0):
            return "이전 시도가 막혀 재시도 대기 중입니다"
        if outcome == "held":
            return None  # 검토(bless) 여부를 매번 다시 확인한다
        return None

    def _deps_sync(self, state: dict) -> str | None:
        pyproject = self.repo / "apps/api/pyproject.toml"
        digest = sha256_file(pyproject) if pyproject.is_file() else ""
        if self.cfg.skip_pip or digest == state.get("pip_hash"):
            return None
        proc = subprocess.run(
            [self.cfg.python, "-m", "pip", "install", "-q", "-e", str(self.repo / "apps/api")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
        )  # fmt: skip
        if proc.returncode != 0:
            return f"의존성 설치 실패: {proc.stderr.strip()[-200:]}"
        self.save_state(pip_hash=digest)
        return None

    def _orchestrator(self, tip: str, token: str) -> dict:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        result_file = self.state_dir / "last-result.json"
        result_file.unlink(missing_ok=True)
        cmd = [
            self.cfg.python, str(self.tools_dir / "shared_db_deploy.py"), "run", "--sha", tip,
            "--repo", self.cfg.repo, "--backup-dir", str(self.cfg.backup_dir),
            "--state-dir", str(self.state_dir), "--pgpass", str(self.cfg.pgpass),
            "--api-root", str(self.repo / "apps/api"), "--result-file", str(result_file),
        ]  # fmt: skip
        if not self.cfg.apply:
            cmd.append("--dry-run")
        keep = (
            *BASE_ENV_KEYS,
            "GITHUB_API_URL",
            "GABEE_DEPLOY_LOOPBACK_TARGET",
            "PYTHONIOENCODING",
        )
        env = {k: v for k, v in os.environ.items() if k in keep}
        env["GITHUB_TOKEN"] = token
        env.setdefault("PYTHONIOENCODING", "utf-8")
        proc = subprocess.run(
            cmd, cwd=self.repo / "apps/api", env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=3600,
        )  # fmt: skip
        for line in proc.stdout.splitlines():
            self.log("  " + line)
        try:
            return json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            tail = (proc.stderr or proc.stdout).strip()[-300:]
            return {
                "outcome": "blocked",
                "message": f"오케스트레이터가 결과 없이 종료했습니다(코드 {proc.returncode}): {tail}",
            }

    def run_once(self) -> dict:
        if not self.cfg.enabled:
            return self._finish(
                "disabled", "에이전트가 비활성 상태입니다(GABEE_AGENT_ENABLED=true 로 켭니다)"
            )
        with file_lock(self.state_dir / "agent.lock") as acquired:
            if not acquired:
                return self._finish("skipped", "이전 에이전트 실행이 아직 진행 중입니다")
            return self._run_locked()

    def _run_locked(self) -> dict:
        halt = self.state_dir / "HALT"
        if halt.exists():
            return self._finish(
                "halted", "이전 배포 실패로 중단 상태입니다 — 원인 해결 후 clear-halt 로 재개합니다"
            )
        try:
            token = self.cfg.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return self._finish("refused", "GitHub 토큰 파일을 읽을 수 없습니다")
        if not token:
            return self._finish("refused", "GitHub 토큰 파일이 비어 있습니다")
        if not self.cfg.pgpass.is_file():
            return self._finish("refused", "pgpass 파일을 찾을 수 없습니다")

        try:
            tip = deploy.GitHubCiVerifier(self.cfg.repo, token).main_tip()
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError, deploy.Refused) as exc:
            return self._finish(
                "skipped", f"GitHub 에서 최신 main 을 확인하지 못했습니다({type(exc).__name__})"
            )
        reason = self._should_skip(tip)
        if reason:
            return self._finish("idle", reason, tip)

        try:
            self._git_sync(tip, token)
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            return self._finish("skipped", f"main 을 체크아웃하지 못했습니다: {exc}", tip)

        problems = self.trust_problems()
        if problems:
            first = self.load_state().get("held_sha") != tip
            self.save_state(last_sha=tip, last_outcome="held", held_reason=problems, held_sha=tip)
            if first:  # 같은 커밋으로 이슈를 반복해서 만들지 않는다
                self._notify_held(token, tip, problems)
            return self._finish(
                "held",
                "배포 도구/신뢰 파일이 검토(bless)된 것과 다릅니다: " + "; ".join(problems),
                tip,
            )

        failure = self._deps_sync(self.load_state())
        if failure:
            self.save_state(
                last_sha=tip,
                last_outcome="blocked",
                last_mode="apply" if self.cfg.apply else "dry",
                retry_after=time.time() + RETRY_BLOCKED_SECONDS,
            )
            return self._finish("blocked", failure, tip)

        self.log(f"배포 시작: 커밋 {tip[:8]} ({'적용' if self.cfg.apply else 'dry-run'})")
        result = self._orchestrator(tip, token)
        outcome = result.get("outcome", "blocked")
        updates = {
            "last_sha": tip, "last_outcome": outcome, "last_mode": "apply" if self.cfg.apply else "dry",
            "last_run": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "held_reason": None,
            "last_message": result.get("message"), "last_backup": result.get("backup"),
            "last_from": result.get("from"), "last_to": result.get("to"),
        }  # fmt: skip
        if outcome == "blocked":
            updates["retry_after"] = time.time() + RETRY_BLOCKED_SECONDS
        if outcome == "skipped":
            updates["last_sha"] = None  # CI 대기 등: 다음 주기에 같은 커밋을 다시 확인한다
        self.save_state(**updates)
        return self._finish(outcome, result.get("message", ""), tip)

    def _notify_held(self, token: str, tip: str, problems: list[str]) -> None:
        body = {"outcome": "held", "message": "배포 도구/신뢰 파일이 검토(bless)된 것과 달라 자동 적용을 멈췄습니다: " + "; ".join(problems) + " — 변경을 리뷰한 뒤 공용 DB PC 에서 `deploy_agent.py bless --sha <커밋> --yes` 를 실행하세요.", "sha": tip, "from": None, "to": None, "backup": None}  # fmt: skip
        try:
            os.environ["GITHUB_TOKEN"] = token
            deploy.notify(
                body, self.cfg.repo, token, f"https://github.com/{self.cfg.repo}/commit/{tip}"
            )
        except (urllib.error.URLError, OSError, KeyError) as exc:
            self.log(f"[warn] held 알림에 실패했습니다: {type(exc).__name__}")
        finally:
            os.environ.pop("GITHUB_TOKEN", None)

    # ---------- 관리자용 ----------
    def status(self) -> dict:
        state = self.load_state()
        backups = (
            sorted(p.name for p in self.cfg.backup_dir.glob("gabee_pg16_deploy_*.dump"))
            if self.cfg.backup_dir.is_dir()
            else []
        )
        halt = self.state_dir / "HALT"
        return {
            "enabled": self.cfg.enabled, "apply": self.cfg.apply,
            "halt": halt.read_text(encoding="utf-8", errors="replace")[:300] if halt.exists() else None,
            "state": state, "latest_backup": backups[-1] if backups else None, "backups": len(backups),
        }  # fmt: skip

    def clear_halt(self) -> bool:
        halt = self.state_dir / "HALT"
        if halt.exists():
            halt.unlink()
            self.save_state(last_sha=None, last_outcome=None)
            return True
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공용 DB PC Pull Agent")
    parser.add_argument(
        "--env-file", type=Path, default=Path(__file__).resolve().parent.parent / "agent.env"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once", help="한 번 실행(작업 스케줄러가 5분마다 호출)")
    sub.add_parser("status", help="상태·마지막 결과·HALT·최근 백업")
    sub.add_parser("clear-halt", help="실패 원인을 해결한 뒤 HALT 해제")
    bless = sub.add_parser("bless", help="검토한 커밋의 배포 도구를 고정하고 신뢰 파일을 승인")
    bless.add_argument("--sha", required=True)
    bless.add_argument("--yes", action="store_true", help="코드를 검토했음을 확인")
    args = parser.parse_args(argv)
    try:
        agent = Agent(Config.load(args.env_file))
    except deploy.Refused as exc:
        print(f"[REFUSED] {exc}")
        return 2

    if args.command == "status":
        print(json.dumps(agent.status(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "clear-halt":
        print("HALT 를 해제했습니다." if agent.clear_halt() else "HALT 가 없습니다.")
        return 0
    if args.command == "bless":
        if not args.yes:
            print(
                "[REFUSED] 해당 커밋의 배포 도구·alembic/env.py 변경을 검토했다면 --yes 를 붙여 다시 실행하세요."
            )
            return 2
        try:
            token = agent.cfg.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            token = None
        changed = agent.bless(args.sha, token)
        print("고정한 배포 도구:", ", ".join(changed) or "(변경 없음)")
        return 0

    outcome = agent.run_once()["outcome"]
    return 2 if outcome == "refused" else (0 if outcome in OK_OUTCOMES else 1)


if __name__ == "__main__":
    sys.exit(main())
