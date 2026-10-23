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
    a.fake["ci"] = deploy.CiVerdict("ok", "CI 성공")
    monkeypatch.setattr(deploy.GitHubCiVerifier, "verify", lambda self, sha: a.fake["ci"])
    monkeypatch.setattr(
        a, "_git_sync", lambda sha, token=None: a.calls.__setitem__("sync", a.calls["sync"] + 1)
    )
    monkeypatch.setattr(a, "trust_problems", lambda: [])
    a.calls["deps"] = 0

    def deps_sync(state):
        a.calls["deps"] += 1

    monkeypatch.setattr(a, "_deps_sync", deps_sync)

    def orchestrator(tip, token):
        a.calls["orchestrator"] += 1
        return dict(a.fake["result"])

    monkeypatch.setattr(a, "_orchestrator", orchestrator)
    a.fake["notify_ok"], a.notified = True, []

    def notify(token, tip, outcome, message):
        a.calls["held"] += outcome == "held"
        a.notified.append((outcome, message))
        return a.fake["notify_ok"]

    monkeypatch.setattr(a, "_notify", notify)
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
    assert agent.calls == {"tip": 0, "sync": 0, "orchestrator": 0, "held": 0, "deps": 0}


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


def write(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def real_checkout(agent, monkeypatch):
    """env.py → app.shared.db → .config, 기능 모델로 이어지는 실제와 같은 모양의 체크아웃을 bless 해 둔다."""
    monkeypatch.delattr(agent, "trust_problems")  # 실제 검사 사용
    make_checkout(agent)
    write(agent.repo / "apps/api", {
        "alembic/env.py": "from app.shared.db import Base, import_all_models" + NL,
        "app/__init__.py": "", "app/shared/__init__.py": "", "app/features/__init__.py": "",
        "app/shared/db.py": "from .config import settings" + NL + "def import_all_models():" + NL + "    from app.features.billing import models" + NL,
        "app/shared/config.py": "settings = 1" + NL,
        "app/shared/mailer.py": "import smtplib" + NL,
        "app/features/billing/__init__.py": "",
        "app/features/billing/models.py": "from sqlalchemy import String" + NL + "from app.shared.db import Base" + NL,
        "alembic/versions/r1.py": '"""r1"""' + NL + "from alembic import op" + NL + "def upgrade():" + NL + "    pass" + NL,
    })  # fmt: skip
    monkeypatch.setattr(agent, "_git_sync", lambda sha, token=None: None)
    agent.bless(TIP)
    assert agent.trust_problems() == []
    return agent.repo / "apps/api"


def test_feature_models_change_freely_but_shared_code_reached_from_env_is_pinned(
    agent, monkeypatch
):
    api = real_checkout(agent, monkeypatch)
    write(api, {
        "app/features/billing/models.py": "from sqlalchemy import Integer" + NL + "from app.shared.db import Base" + NL,
        "app/shared/mailer.py": "import os" + NL,  # env.py 에서 닿지 않는 공통 코드는 고정 대상이 아니다
        "alembic/versions/r2.py": '"""r2"""' + NL + "from alembic import op" + NL + "def upgrade():" + NL + "    pass" + NL,
    })  # fmt: skip
    assert agent.trust_problems() == []  # 평소 기능·마이그레이션 개발은 bless 가 필요 없다
    write(api, {"app/shared/config.py": "import os" + NL + "os.system('x')" + NL})
    assert any(
        "배포 신뢰 파일이 바뀜: apps/api/app/shared/config.py" in p for p in agent.trust_problems()
    )


def test_model_that_pulls_in_other_code_or_unsafe_python_is_held(agent, monkeypatch):
    api = real_checkout(agent, monkeypatch)
    models = api / "app/features/billing/models.py"
    write(api, {"app/features/billing/service.py": "x = 1" + NL})
    models.write_text("from app.features.billing import service" + NL, encoding="utf-8")
    assert any(
        "검토(bless)되지 않음: apps/api/app/features/billing/service.py" in p
        for p in agent.trust_problems()
    )  # 모델이 끌어들인 코드는 고정 대상이 된다
    models.write_text("import subprocess" + NL, encoding="utf-8")
    assert any("unsafe-import" in p for p in agent.trust_problems())
    models.write_text("import app.nowhere" + NL, encoding="utf-8")
    assert any("찾을 수 없는 app 모듈: app.nowhere" in p for p in agent.trust_problems())


def test_unsafe_revision_or_library_shadowing_module_is_held(agent, monkeypatch):
    api = real_checkout(agent, monkeypatch)
    write(
        api, {"alembic/versions/r2.py": "import os" + NL + "def upgrade():" + NL + "    pass" + NL}
    )
    assert any(
        "리비전의 위험한 파이썬" in p and "unsafe-import" in p for p in agent.trust_problems()
    )
    (api / "alembic/versions/r2.py").unlink()
    write(api, {"sqlalchemy.py": "import os" + NL})
    assert any("라이브러리를 가릴 수 있음: sqlalchemy.py" in p for p in agent.trust_problems())


def test_dependency_or_build_change_is_held_before_pip_or_orchestrator_runs(agent, monkeypatch):
    api = real_checkout(agent, monkeypatch)
    original = (api / "pyproject.toml").read_text(encoding="utf-8")
    write(api, {"pyproject.toml": "[project]" + NL + "dependencies = ['evil']" + NL})
    held = agent.run_once()
    assert held["outcome"] == "held" and "pyproject.toml" in held["message"]
    assert agent.calls["deps"] == 0 and agent.calls["orchestrator"] == 0
    # 빌드 스크립트가 새로 생김
    write(api, {"pyproject.toml": original, "setup.py": "import os" + NL})
    held = agent.run_once()
    assert held["outcome"] == "held" and "setup.py" in held["message"]
    assert agent.calls["deps"] == 0 and agent.calls["orchestrator"] == 0


def test_unparsable_or_failing_trust_check_is_fail_closed(agent, monkeypatch):
    api = real_checkout(agent, monkeypatch)
    write(api, {"app/features/billing/models.py": "def (" + NL})
    held = agent.run_once()
    assert held["outcome"] == "held" and "신뢰 검사를 할 수 없음(SyntaxError)" in held["message"]
    assert agent.calls["deps"] == 0 and agent.calls["orchestrator"] == 0


def test_held_notification_failure_keeps_holding_and_retries_the_issue(agent, monkeypatch):
    monkeypatch.setattr(agent, "trust_problems", lambda: ["배포 도구가 바뀜: x"])
    agent.fake["notify_ok"] = False  # GitHub 이슈 생성 실패
    assert agent.run_once()["outcome"] == "held" and agent.run_once()["outcome"] == "held"
    assert agent.calls["held"] == 2  # 알림이 실패했으므로 다음 주기에 다시 알린다
    agent.fake["notify_ok"] = True
    agent.run_once()
    agent.run_once()
    assert agent.calls["held"] == 3
    # 그동안 배포는 하지 않았다
    assert agent.calls["deps"] == 0 and agent.calls["orchestrator"] == 0


def test_notify_failure_of_any_kind_is_logged_and_not_raised(agent, monkeypatch):
    monkeypatch.undo()

    def boom(*args, **kwargs):
        raise ValueError("GitHub 응답 이상")

    monkeypatch.setattr(deploy, "notify", boom)
    assert agent._notify("t", TIP, "held", "m") is False
    assert "GITHUB_TOKEN" not in __import__("os").environ


def test_dependencies_are_installed_only_after_the_commit_ci_is_green(agent):
    agent.fake["ci"] = deploy.CiVerdict("pending", "CI 진행 중")
    assert agent.run_once()["outcome"] == "skipped"
    for status in ("not_green", "unknown"):  # CI 실패, GitHub API 오류
        agent.save_state(last_sha=None)
        agent.fake["ci"] = deploy.CiVerdict(status, "확인 실패")
        assert agent.run_once()["outcome"] == "blocked" and agent.notified[-1][0] == "blocked"
    assert agent.calls["deps"] == 0 and agent.calls["orchestrator"] == 0
    agent.save_state(retry_after=0)
    agent.fake["ci"] = deploy.CiVerdict("ok", "CI 성공")
    assert agent.run_once()["outcome"] == "success"
    assert agent.calls["deps"] == 1 and agent.calls["orchestrator"] == 1


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
