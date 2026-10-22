"""Pull Agent 전체 경로 e2e — 격리 PostgreSQL 16(가짜 공용 DB) + 로컬 가짜 GitHub API + 로컬 git 저장소.

GABEE_DEPLOY_E2E=1 일 때만 실행한다. 실제 공용 DB(192.168.0.44)·GitHub 에는 접속하지 않는다:
- 오케스트레이터 서브프로세스는 GABEE_DEPLOY_LOOPBACK_TARGET(루프백만 허용)으로 이 테스트의 컨테이너를 가리키고,
- GitHub API 는 GITHUB_API_URL(루프백만 허용)로 이 파일의 가짜 서버를 가리킨다.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
agent_module = __import__("deploy_agent")  # scripts/ 는 패키지가 아니라 경로를 추가한 뒤 불러온다

from tests.test_shared_db_deploy_e2e import (  # noqa: E402, F401  (fake_shared 는 pytest 픽스처)
    HEAD,
    PRIOR,
    alembic_copy,
    conn,
    counts,
    deploy_backups,
    fake_shared,
    reset_db,
    revision,
    revision_of,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("GABEE_DEPLOY_E2E") != "1", reason="GABEE_DEPLOY_E2E=1 일 때만 실행(Docker 필요)"
)

API_ROOT = Path(__file__).resolve().parents[1]
REPO = "o/r"
NL = chr(10)


class FakeGitHub:
    """배포에 쓰이는 GitHub API 최소 구현: main 최신 커밋, CI 실행/Job, 이슈."""

    def __init__(self) -> None:
        self.tip, self.ci, self.issues, self.requests = None, "green", [], []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, body, code=200):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def do_GET(self):
                path = urlparse(self.path).path
                owner.requests.append(("GET", path))
                if path.endswith("/branches/main"):
                    return self._send({"commit": {"sha": owner.tip}})
                if path.endswith("/actions/runs"):
                    run = {"id": 9, "run_number": 1, "head_sha": owner.tip, "head_branch": "main", "event": "push",
                           "path": ".github/workflows/ci-check.yml@refs/heads/main", "head_repository": {"full_name": REPO}}  # fmt: skip
                    status, conclusion = {
                        "green": ("completed", "success"),
                        "red": ("completed", "failure"),
                        "pending": ("in_progress", None),
                    }[owner.ci]
                    return self._send(
                        {"workflow_runs": [{**run, "status": status, "conclusion": conclusion}]}
                    )
                if path.endswith("/jobs"):
                    return self._send(
                        {
                            "jobs": [
                                {"name": n, "conclusion": "success"}
                                for n in ("api", "api-postgres", "mobile")
                            ]
                        }
                    )
                if "/commits/" in path:
                    return self._send(
                        {
                            "commit": {
                                "committer": {
                                    "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                                }
                            }
                        }
                    )
                if path.endswith("/issues"):
                    return self._send([i for i in owner.issues if i["state"] == "open"])
                self._send({"message": "not found"}, 404)

            def do_POST(self):
                path = urlparse(self.path).path
                owner.requests.append(("POST", path))
                body = self._body()
                if path.endswith("/labels"):
                    return self._send({}, 201)
                if path.endswith("/issues"):
                    owner.issues.append(
                        {
                            "number": len(owner.issues) + 1,
                            "state": "open",
                            "title": body.get("title"),
                            "body": body.get("body"),
                            "comments": [],
                        }
                    )
                    return self._send(owner.issues[-1], 201)
                if path.endswith("/comments"):
                    number = int(path.split("/")[-2])
                    owner.issues[number - 1]["comments"].append(body.get("body"))
                    return self._send({}, 201)
                self._send({}, 404)

            def do_PATCH(self):
                path = urlparse(self.path).path
                number = int(path.split("/")[-1])
                owner.issues[number - 1]["state"] = self._body().get("state", "open")
                self._send({})

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def git(cwd, *args):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def commit(origin, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        path = origin / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", message)
    return git(origin, "rev-parse", "HEAD")


@pytest.fixture
def world(fake_shared, tmp_path, monkeypatch):  # noqa: F811
    """origin(main 에 현재 작업 트리를 커밋한 로컬 저장소) + 가짜 GitHub + 에이전트."""
    github = FakeGitHub()
    origin = tmp_path / "origin"
    shutil.copytree(
        API_ROOT, origin / "apps" / "api",
        ignore=shutil.ignore_patterns(".venv", "__pycache__", "data", ".pytest_cache", ".ruff_cache", "*.egg-info", ".env", ".env.*"),
    )  # fmt: skip
    (origin / "apps" / "api" / ".env.example").write_text("", encoding="utf-8")
    git(origin, "init", "-q", "-b", "main")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "t")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "main")
    github.tip = git(origin, "rev-parse", "HEAD")

    home = tmp_path / "home"
    tools = home / "agent"
    tools.mkdir(parents=True)
    for rel in agent_module.TOOL_FILES:
        shutil.copyfile(API_ROOT / "scripts" / Path(rel).name, tools / Path(rel).name)
    token = home / "secrets" / "github-token"
    token.parent.mkdir()
    token.write_text("test-token", encoding="utf-8")
    target = fake_shared["target"]
    monkeypatch.setenv("GITHUB_API_URL", github.url)
    monkeypatch.setenv("GABEE_DEPLOY_LOOPBACK_TARGET", f"127.0.0.1,{target.port},gabee,gabee_migrator,{target.tools_host},{target.tools_port},{target.docker_network}")  # fmt: skip

    def make_agent(apply=True):
        cfg = agent_module.Config(
            repo=REPO, home=home, backup_dir=tmp_path / "backups", pgpass=fake_shared["pgpass"], token_file=token,
            git_url=str(origin), enabled=True, apply=apply, python=sys.executable, skip_pip=True,
        )  # fmt: skip
        return agent_module.Agent(cfg, tools_dir=tools)

    agent = make_agent()
    agent.bless(github.tip)
    yield {
        "github": github,
        "origin": origin,
        "agent": agent,
        "make_agent": make_agent,
        "tools": tools,
        "tmp": tmp_path,
        "fs": fake_shared,
    }
    github.close()


def test_agent_deploys_exact_main_commit_once_and_survives_restart(world):
    fs, agent, github = world["fs"], world["agent"], world["github"]
    reset_db(fs)
    before = counts(fs)

    result = agent.run_once()

    assert result["outcome"] == "success", result["message"]
    assert revision_of(fs) == [HEAD] and counts(fs) == before
    assert len(deploy_backups(world["tmp"])) == 1
    assert (
        agent.load_state()["last_sha"] == github.tip
        and agent.load_state()["last_outcome"] == "success"
    )
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=agent.repo, capture_output=True, text=True
        ).stdout.strip()
        == github.tip
    )

    reborn = world["make_agent"]()  # PC 재부팅 후 새 프로세스 — 같은 커밋을 다시 적용하지 않는다
    assert reborn.run_once()["outcome"] == "idle"
    assert len(deploy_backups(world["tmp"])) == 1 and revision_of(fs) == [HEAD]


def test_dry_run_mode_backs_up_and_rehearses_but_never_applies(world):
    fs = world["fs"]
    reset_db(fs)
    result = world["make_agent"](apply=False).run_once()
    assert result["outcome"] == "dry_run_ok", result["message"]
    assert revision_of(fs) == [PRIOR] and len(deploy_backups(world["tmp"])) == 1


def test_ci_pending_waits_then_deploys_and_ci_failure_blocks_with_an_issue(world):
    fs, agent, github = world["fs"], world["agent"], world["github"]
    reset_db(fs)
    github.ci = "pending"
    assert agent.run_once()["outcome"] == "skipped"
    assert revision_of(fs) == [PRIOR] and deploy_backups(world["tmp"]) == [] and github.issues == []

    github.ci = "red"
    blocked = agent.run_once()
    assert blocked["outcome"] == "blocked"
    assert revision_of(fs) == [PRIOR] and deploy_backups(world["tmp"]) == []
    assert len(github.issues) == 1 and "blocked" in github.issues[0]["body"]

    github.ci = "green"
    agent.save_state(retry_after=0)  # 재시도 대기 시간이 지났다고 가정
    assert agent.run_once()["outcome"] == "success"
    assert (
        revision_of(fs) == [HEAD] and github.issues[0]["state"] == "closed"
    )  # 성공하면 실패 이슈가 자동으로 닫힌다


def test_changed_deploy_tools_are_held_until_a_human_blesses_them(world):
    fs, agent, github, origin = world["fs"], world["agent"], world["github"], world["origin"]
    reset_db(fs)
    tool = (origin / "apps/api/scripts/shared_db_deploy.py").read_text(encoding="utf-8")
    github.tip = commit(
        origin,
        {"apps/api/scripts/shared_db_deploy.py": tool + NL + "# 몰래 바꾼 배포 코드" + NL},
        "배포 도구 변경",
    )

    held = agent.run_once()
    assert held["outcome"] == "held"
    assert (
        revision_of(fs) == [PRIOR] and deploy_backups(world["tmp"]) == []
    )  # 자격증명으로 실행하지 않았다
    assert len(github.issues) == 1 and "bless" in github.issues[0]["body"]
    assert (
        agent.run_once()["outcome"] == "held" and len(github.issues) == 1
    )  # 같은 커밋으로 이슈 반복 없음

    changed = agent.bless(github.tip)  # 관리자가 검토 후 승인
    assert changed == ["shared_db_deploy.py"]
    assert agent.run_once()["outcome"] == "success" and revision_of(fs) == [HEAD]


def test_python_migration_that_touches_files_or_network_is_never_run(world):
    fs, agent, github, origin = world["fs"], world["agent"], world["github"], world["origin"]
    reset_db(fs)
    evil = revision("e1", HEAD, "pass").replace(
        "from alembic import op", "import os\nfrom alembic import op"
    )
    github.tip = commit(origin, {"apps/api/alembic/versions/e1_evil.py": evil}, "악성 마이그레이션")
    blocked = agent.run_once()
    assert blocked["outcome"] == "blocked" and "unsafe-import" in blocked["message"]
    assert revision_of(fs) == [PRIOR] and deploy_backups(world["tmp"]) == []


def test_failed_apply_halts_the_agent_until_a_human_clears_it(world):
    fs, agent, github, origin = world["fs"], world["agent"], world["github"], world["origin"]
    reset_db(fs)
    body = "op.execute(\"DO $$ BEGIN IF current_database() = 'gabee' THEN RAISE EXCEPTION 'boom'; END IF; END $$\")"
    github.tip = commit(
        origin,
        {"apps/api/alembic/versions/g1_boom.py": revision("g1", HEAD, body)},
        "실제 DB 에서만 실패하는 마이그레이션",
    )

    failed = agent.run_once()
    assert failed["outcome"] == "failed"
    assert revision_of(fs) == [PRIOR]  # 한 트랜잭션이라 전체 롤백
    assert (agent.state_dir / "HALT").exists() and agent.status()["halt"]
    requests_before = len(world["github"].requests)
    assert agent.run_once()["outcome"] == "halted"  # HALT 중에는 GitHub 에도 가지 않는다
    assert len(world["github"].requests) == requests_before

    (world["origin"] / "apps/api/alembic/versions/g1_boom.py").unlink()  # 원인 해결(수정 커밋)
    github.tip = commit(origin, {"README.txt": "fix"}, "원인 제거")
    assert agent.clear_halt() is True
    assert agent.run_once()["outcome"] == "success" and revision_of(fs) == [HEAD]


def test_commits_on_other_branches_are_never_fetched_or_deployed(world):
    fs, agent, github, origin = world["fs"], world["agent"], world["github"], world["origin"]
    reset_db(fs)
    main_sha = github.tip
    git(origin, "switch", "-q", "-c", "someone-elses-branch")
    commit(
        origin,
        {"apps/api/alembic/versions/z9_branch_only.py": revision("z9", HEAD, "pass")},
        "다른 팀원 브랜치의 마이그레이션",
    )
    git(origin, "switch", "-q", "main")

    assert agent.run_once()["outcome"] == "success"
    assert revision_of(fs) == [HEAD]  # 브랜치의 z9 는 적용되지 않았다
    assert not (agent.repo / "apps/api/alembic/versions/z9_branch_only.py").exists()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=agent.repo, capture_output=True, text=True
        ).stdout.strip()
        == main_sha
    )
    assert alembic_copy  # (임포트 유지: 다른 e2e 와 헬퍼 공유)
