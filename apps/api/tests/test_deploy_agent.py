"""공용 DB PC Pull Agent(scripts/deploy_agent.py) 단위 테스트 — Docker·DB 없이 실제 git 저장소만 쓴다."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import deploy_agent as agent_module  # noqa: E402
import shared_db_deploy as deploy  # noqa: E402

TIP = "a" * 40
NL = chr(10)


def make_config(tmp_path, **over):
    token = tmp_path / "token"
    token.write_text("ghp_SECRET_TOKEN_VALUE", encoding="utf-8")
    pgpass = tmp_path / "pgpass"
    pgpass.write_text("x", encoding="utf-8")
    values = dict(
        repo="o/r", home=tmp_path / "home", backup_dir=tmp_path / "backups", pgpass=pgpass,
        token_file=token, git_url=str(tmp_path / "origin"), enabled=True, apply=True,
    )  # fmt: skip
    values.update(over)
    return agent_module.Config(**values)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("deploy_agent.py", "shared_db_deploy.py", "migration_risk.py"):
        (tools / name).write_text(f"# {name}", encoding="utf-8")
    a = agent_module.Agent(make_config(tmp_path), tools_dir=tools)
    a.calls = {"tip": 0, "sync": 0, "orchestrator": 0, "held": 0}
    state = {"tip": TIP, "result": {"outcome": "success", "message": "ok", "from": "a", "to": "b"}}
    a.fake = state

    def main_tip(self):
        a.calls["tip"] += 1
        return a.fake["tip"]

    monkeypatch.setattr(deploy.GitHubCiVerifier, "main_tip", main_tip)
    monkeypatch.setattr(
        a, "_git_sync", lambda sha, token=None: a.calls.__setitem__("sync", a.calls["sync"] + 1)
    )
    monkeypatch.setattr(a, "trust_problems", lambda: [])
    monkeypatch.setattr(a, "_deps_sync", lambda state: None)

    def orchestrator(tip, token):
        a.calls["orchestrator"] += 1
        return dict(a.fake["result"])

    monkeypatch.setattr(a, "_orchestrator", orchestrator)
    monkeypatch.setattr(
        a, "_notify_held", lambda *args: a.calls.__setitem__("held", a.calls["held"] + 1)
    )
    return a


# ---------- 설정 ----------
def test_config_requires_paths_and_defaults_to_disabled(tmp_path):
    with pytest.raises(deploy.Refused):
        agent_module.Config.load(environ={})
    cfg = agent_module.Config.load(
        environ={"GABEE_DEPLOY_HOME": str(tmp_path), "GABEE_BACKUP_DIR": str(tmp_path / "b"), "GABEE_PGPASS": str(tmp_path / "p")}
    )  # fmt: skip
    assert cfg.enabled is False and cfg.apply is False and cfg.repo == "kangminhun/gabee"
    assert cfg.git_url == "https://github.com/kangminhun/gabee.git"


def test_env_file_is_read_but_real_environment_wins(tmp_path):
    env_file = tmp_path / "agent.env"
    env_file.write_text(
        NL.join(["# 주석", f"GABEE_DEPLOY_HOME={tmp_path}", f"GABEE_BACKUP_DIR={tmp_path}/b", f"GABEE_PGPASS={tmp_path}/p", "GABEE_AGENT_ENABLED=true", "GABEE_AGENT_APPLY=false"]),
        encoding="utf-8",
    )  # fmt: skip
    cfg = agent_module.Config.load(env_file, environ={"GABEE_AGENT_APPLY": "true"})
    assert cfg.enabled is True and cfg.apply is True


# ---------- 실행 결정 ----------
def test_disabled_agent_does_nothing(agent):
    agent.cfg.enabled = False
    assert agent.run_once()["outcome"] == "disabled"
    assert agent.calls == {"tip": 0, "sync": 0, "orchestrator": 0, "held": 0}


def test_halt_stops_everything_without_calling_github(agent):
    agent.state_dir.mkdir(parents=True)
    (agent.state_dir / "HALT").write_text("이전 실패", encoding="utf-8")
    assert agent.run_once()["outcome"] == "halted"
    assert agent.calls["tip"] == 0
    assert agent.clear_halt() is True and agent.clear_halt() is False


def test_missing_token_or_pgpass_is_refused(agent):
    agent.cfg.token_file.unlink()
    assert agent.run_once()["outcome"] == "refused"
    agent.cfg.token_file.write_text("t", encoding="utf-8")
    agent.cfg.pgpass.unlink()
    assert agent.run_once()["outcome"] == "refused" and agent.calls["tip"] == 0


def test_new_commit_is_deployed_once_and_not_repeated(agent):
    first = agent.run_once()
    assert first["outcome"] == "success" and agent.calls["orchestrator"] == 1
    second = agent.run_once()  # 같은 커밋: 중복 적용 방지
    assert (
        second["outcome"] == "idle"
        and agent.calls["orchestrator"] == 1
        and agent.calls["sync"] == 1
    )
    agent.fake["tip"] = "b" * 40  # 새 커밋이 병합됨
    assert agent.run_once()["outcome"] == "success" and agent.calls["orchestrator"] == 2


def test_state_survives_restart_so_reboot_does_not_redeploy(agent, tmp_path):
    agent.run_once()
    reborn = agent_module.Agent(agent.cfg, tools_dir=agent.tools_dir)  # PC 재부팅 후 새 프로세스
    assert reborn.load_state()["last_sha"] == TIP and reborn._should_skip(TIP) is not None


def test_ci_pending_is_retried_on_the_next_tick(agent):
    agent.fake["result"] = {"outcome": "skipped", "message": "CI 진행 중"}
    assert agent.run_once()["outcome"] == "skipped"
    agent.fake["result"] = {"outcome": "success", "message": "ok"}
    assert agent.run_once()["outcome"] == "success"  # 같은 커밋을 다시 확인해 배포
    assert agent.calls["orchestrator"] == 2


def test_blocked_commit_is_retried_only_after_the_backoff(agent):
    agent.fake["result"] = {"outcome": "blocked", "message": "백업 실패"}
    agent.run_once()
    assert agent.run_once()["outcome"] == "idle" and agent.calls["orchestrator"] == 1  # 대기 중
    agent.save_state(retry_after=time.time() - 1)
    agent.fake["result"] = {"outcome": "success", "message": "ok"}
    assert agent.run_once()["outcome"] == "success" and agent.calls["orchestrator"] == 2


def test_dry_run_result_is_redone_when_apply_is_switched_on(agent):
    agent.cfg.apply = False
    agent.fake["result"] = {"outcome": "dry_run_ok", "message": "dry"}
    agent.run_once()
    assert agent.run_once()["outcome"] == "idle"  # 같은 모드는 반복하지 않음
    agent.cfg.apply = True
    agent.fake["result"] = {"outcome": "success", "message": "ok"}
    assert agent.run_once()["outcome"] == "success" and agent.calls["orchestrator"] == 2


def test_github_failure_is_a_quiet_skip_not_a_failure(agent, monkeypatch):
    def boom(self):
        raise TimeoutError

    monkeypatch.setattr(deploy.GitHubCiVerifier, "main_tip", boom)
    assert agent.run_once()["outcome"] == "skipped" and agent.calls["orchestrator"] == 0


# ---------- 신뢰: 배포 도구가 바뀌면 멈춘다 ----------
def test_changed_deploy_tools_hold_the_deployment_and_notify_once(agent, monkeypatch):
    monkeypatch.setattr(agent, "trust_problems", lambda: ["배포 도구가 바뀜: shared_db_deploy.py"])
    first = agent.run_once()
    assert first["outcome"] == "held" and agent.calls["orchestrator"] == 0
    assert agent.run_once()["outcome"] == "held"
    assert agent.calls["held"] == 1  # 같은 커밋으로 이슈를 반복해서 만들지 않는다
    agent.fake["tip"] = "c" * 40
    agent.run_once()
    assert agent.calls["held"] == 2


def make_checkout(agent):
    for rel in (*agent_module.TOOL_FILES, *agent_module.TRUST_FILES):
        path = agent.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}", encoding="utf-8")
        if rel in agent_module.TOOL_FILES:
            (agent.tools_dir / Path(rel).name).write_text(f"# {rel}", encoding="utf-8")


def test_trust_check_needs_bless_then_detects_every_change(agent, monkeypatch):
    monkeypatch.undo()  # 실제 trust_problems 사용
    make_checkout(agent)
    assert any("검토(bless)되지 않음" in p for p in agent.trust_problems())  # 최초에는 승인 필요

    trust = {rel: agent_module.sha256_file(agent.repo / rel) for rel in agent_module.TRUST_FILES}
    agent.state_dir.mkdir(parents=True, exist_ok=True)
    (agent.state_dir / "trust.json").write_text(json.dumps(trust), encoding="utf-8")
    assert agent.trust_problems() == []

    (agent.repo / "apps/api/alembic/env.py").write_text(
        "# 변경", encoding="utf-8"
    )  # 신뢰 파일 변경
    assert any("env.py" in p for p in agent.trust_problems())
    (agent.repo / "apps/api/alembic/env.py").write_text(
        "# apps/api/alembic/env.py", encoding="utf-8"
    )
    assert agent.trust_problems() == []

    (agent.repo / "apps/api/scripts/shared_db_deploy.py").write_text(
        "# 악성 변경", encoding="utf-8"
    )  # 배포 도구 변경
    assert any("shared_db_deploy.py" in p for p in agent.trust_problems())


def test_bless_pins_the_reviewed_tools_and_clears_held(agent, monkeypatch):
    monkeypatch.undo()
    make_checkout(agent)
    (agent.repo / "apps/api/scripts/migration_risk.py").write_text(
        "# 검토한 새 버전", encoding="utf-8"
    )
    monkeypatch.setattr(agent, "_git_sync", lambda sha, token=None: None)
    agent.save_state(held_reason=["x"])
    changed = agent.bless("a" * 40)
    assert changed == ["migration_risk.py"]
    assert (agent.tools_dir / "migration_risk.py").read_text(encoding="utf-8") == "# 검토한 새 버전"
    assert agent.trust_problems() == [] and agent.load_state()["held_reason"] is None


# ---------- 비밀 처리 ----------
def test_token_is_only_in_environment_never_in_argv_state_or_logs(agent, monkeypatch, capsys):
    monkeypatch.undo()
    cfg = make_config(agent.cfg.home.parent, git_url="https://github.com/o/r.git")
    a = agent_module.Agent(cfg, tools_dir=agent.tools_dir)
    env = a._git_env("ghp_SECRET_TOKEN_VALUE")
    assert env["GIT_CONFIG_COUNT"] == "1" and "ghp_SECRET_TOKEN_VALUE" not in "".join(
        env.values()
    )  # base64 로만
    assert "SECRET" not in " ".join(k for k in env)
    assert a._git_env(None).get("GIT_CONFIG_COUNT") is None
    local = agent_module.Agent(make_config(agent.cfg.home.parent), tools_dir=agent.tools_dir)
    assert "GIT_CONFIG_COUNT" not in local._git_env(
        "ghp_SECRET_TOKEN_VALUE"
    )  # github.com 이 아니면 토큰을 보내지 않는다


def test_orchestrator_gets_a_minimal_environment_plus_only_the_token(agent, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("SOME_OTHER_SECRET", "leak-me")
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["env"] = cmd, kwargs["env"]
        Path(cmd[cmd.index("--result-file") + 1]).write_text(
            json.dumps({"outcome": "noop", "message": "m"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="line", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    agent.cfg.apply = False
    result = agent._orchestrator(TIP, "ghp_SECRET_TOKEN_VALUE")
    assert result["outcome"] == "noop"
    assert (
        "SOME_OTHER_SECRET" not in seen["env"]
        and seen["env"]["GITHUB_TOKEN"] == "ghp_SECRET_TOKEN_VALUE"
    )
    assert "ghp_SECRET_TOKEN_VALUE" not in " ".join(seen["cmd"]) and "--dry-run" in seen["cmd"]
    assert seen["cmd"][1] == str(agent.tools_dir / "shared_db_deploy.py")  # 고정된 복사본으로 실행


# ---------- 동시 실행 ----------
def test_file_lock_allows_only_one_agent_at_a_time(tmp_path):
    lock = tmp_path / "agent.lock"
    with agent_module.file_lock(lock) as first:
        with agent_module.file_lock(lock) as second:
            assert first is True and second is False
    with agent_module.file_lock(lock) as again:
        assert again is True


def test_overlapping_run_is_skipped_not_run_twice(agent):
    with agent_module.file_lock(agent.state_dir / "agent.lock"):
        assert agent.run_once()["outcome"] == "skipped" and agent.calls["orchestrator"] == 0


# ---------- 실제 git: 정확한 main 커밋만 ----------
def git(cwd, *args):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def origin(tmp_path):
    repo = tmp_path / "origin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "main.txt").write_text("main 1")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "main 1")
    return repo


def test_checkout_is_the_exact_main_commit_and_never_a_branch_or_pr(tmp_path, origin):
    main_sha = git(origin, "rev-parse", "HEAD")
    git(origin, "switch", "-q", "-c", "evil-branch")
    (origin / "evil.txt").write_text("PR 의 악성 코드")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "evil")
    evil_sha = git(origin, "rev-parse", "HEAD")
    git(origin, "switch", "-q", "main")

    a = agent_module.Agent(make_config(tmp_path, git_url=str(origin)), tools_dir=tmp_path)
    a._git_sync(main_sha)
    assert git(a.repo, "rev-parse", "HEAD") == main_sha and not (a.repo / "evil.txt").exists()

    with pytest.raises(
        RuntimeError
    ):  # 브랜치 커밋은 main 이력에 없으므로 가져오지도 체크아웃하지도 않는다
        a._git_sync(evil_sha)
    assert git(a.repo, "rev-parse", "HEAD") == main_sha


def test_checkout_follows_new_main_commits_and_cleans_leftovers(tmp_path, origin):
    first = git(origin, "rev-parse", "HEAD")
    a = agent_module.Agent(make_config(tmp_path, git_url=str(origin)), tools_dir=tmp_path)
    a._git_sync(first)
    (a.repo / "leftover.txt").write_text("남은 파일")  # 이전 실행의 잔여물
    (origin / "main.txt").write_text("main 2")
    git(origin, "commit", "-qam", "main 2")
    second = git(origin, "rev-parse", "HEAD")
    a._git_sync(second)
    assert git(a.repo, "rev-parse", "HEAD") == second and not (a.repo / "leftover.txt").exists()
    assert (a.repo / "main.txt").read_text() == "main 2"
