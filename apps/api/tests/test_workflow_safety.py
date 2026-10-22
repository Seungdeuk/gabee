"""공용 DB 자동 배포 워크플로우의 보안 경계를 지키는 정적 검사(내부망 러너·DB 가 PR 코드에 닿지 않게)."""

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPLOY = "deploy-shared-db.yml"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import shared_db_deploy as deploy  # noqa: E402


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_only_the_deploy_workflow_may_use_the_self_hosted_runner():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        uses_runner = re.search(r"self-hosted|gabee-db-deploy", text)
        if path.name == DEPLOY:
            assert uses_runner
        else:
            assert not uses_runner, f"{path.name} 이(가) 내부망 self-hosted 러너를 사용합니다"


def test_deploy_workflow_triggers_are_limited_to_main_ci_completion_and_manual_dispatch():
    triggered = triggers(load(DEPLOY))
    assert set(triggered) == {"workflow_run", "workflow_dispatch"}
    assert triggered["workflow_run"]["workflows"] == ["CI Check"]
    assert triggered["workflow_run"]["branches"] == ["main"]
    assert triggered["workflow_run"]["types"] == ["completed"]


def test_deploy_job_is_gated_by_kill_switch_ci_conclusion_and_main():
    job = load(DEPLOY)["jobs"]["deploy"]
    condition = job["if"]
    for required in (
        "vars.SHARED_DB_DEPLOY_ENABLED == 'true'",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_branch == 'main'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.ref == 'refs/heads/main'",
    ):
        assert required in condition


def test_deploy_runs_one_at_a_time_and_never_cancels_midway():
    workflow = load(DEPLOY)
    assert workflow["concurrency"] == {"group": "shared-db-deploy", "cancel-in-progress": False}


def test_deploy_permissions_and_secrets_are_minimal():
    workflow = load(DEPLOY)
    assert workflow["permissions"] == {"contents": "read", "actions": "read", "issues": "write"}
    text = (WORKFLOWS / DEPLOY).read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
    assert "pull_request" not in text.replace("pull_request 계열", "")
    assert "continue-on-error" not in text


def test_deploy_checks_out_exactly_the_verified_commit_without_credentials():
    steps = load(DEPLOY)["jobs"]["deploy"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ env.DEPLOY_SHA }}"
    assert checkout["with"]["persist-credentials"] is False


def test_ci_workflow_matches_what_the_deployer_requires():
    ci = load("ci-check.yml")
    assert ci["name"] == "CI Check"
    assert set(deploy.CI_REQUIRED_JOBS) <= set(ci["jobs"])
    assert deploy.CI_WORKFLOW_PATH == ".github/workflows/ci-check.yml"


def test_deployed_commit_is_the_same_sha_for_checkout_and_deployer():
    job = load(DEPLOY)["jobs"]["deploy"]
    assert job["env"]["DEPLOY_SHA"] == "${{ github.event.workflow_run.head_sha || github.sha }}"
    deploy_step = next(s for s in job["steps"] if "shared_db_deploy.py" in s.get("run", ""))
    assert "--sha $env:DEPLOY_SHA" in deploy_step["run"]
    assert "--repo $env:GITHUB_REPOSITORY" in deploy_step["run"]
