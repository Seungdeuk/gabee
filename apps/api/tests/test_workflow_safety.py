"""GitHub Actions 보안 경계 정적 검사.

공용 DB 배포는 GitHub Self-hosted Runner 가 아니라 공용 DB PC 의 Pull Agent(scripts/deploy_agent.py)가 한다.
러너가 없어야 협업자의 브랜치·PR 워크플로우가 내부망이나 DB 자격증명에 닿을 경로 자체가 생기지 않는다.
"""

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import shared_db_deploy as deploy  # noqa: E402


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_no_workflow_may_use_a_self_hosted_runner():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"self-hosted|gabee-db-deploy", text), (
            f"{path.name} 이(가) self-hosted 러너를 사용합니다"
        )
        for name, job in (yaml.safe_load(text).get("jobs") or {}).items():
            runs_on = job.get("runs-on")
            labels = runs_on if isinstance(runs_on, list) else [runs_on]
            assert all(
                str(label).startswith(("ubuntu-", "windows-", "macos-")) for label in labels
            ), f"{path.name}:{name} 의 runs-on 이 GitHub 호스티드 러너가 아닙니다: {runs_on}"


def test_there_is_no_db_deploy_workflow_so_branches_cannot_trigger_deployments():
    assert not (WORKFLOWS / "deploy-shared-db.yml").exists()
    for path in WORKFLOWS.glob("*.yml"):
        assert "shared_db_deploy" not in path.read_text(encoding="utf-8")


def test_workflows_never_reference_db_secrets_or_the_shared_host():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"192\.168\.0\.44|gabee_migrator|pgpass|SHARED_DB", text), path.name
        assert set(re.findall(r"secrets\.(\w+)", text)) <= {"GITHUB_TOKEN"}, path.name


def test_ci_workflow_matches_what_the_deployer_requires():
    ci = load("ci-check.yml")
    assert ci["name"] == "CI Check"
    assert set(deploy.CI_REQUIRED_JOBS) <= set(ci["jobs"])
    assert deploy.CI_WORKFLOW_PATH == ".github/workflows/ci-check.yml"
    triggers = ci.get("on") or ci.get(True)
    assert "push" in triggers and "pull_request" in triggers
