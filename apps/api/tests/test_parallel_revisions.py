"""5명이 서로 다른 브랜치에서 Alembic 리비전을 병렬로 작성하는 운영 정책 시뮬레이션(실제 git 사용).

각 브랜치는 혼자서는 단일 head 로 통과하고, 병합 결과(PR 의 merge ref 와 같은 상태)에서 head 가 둘이 되면
단일 head 검사(CI `api-postgres`)가 실패해야 하며, 뒤에 병합되는 쪽이 down_revision 을 옮기면 통과해야 한다.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "scripts"))
import check_alembic_migrations as heads_check  # noqa: E402

REVISION = '"""{name}"""\nrevision = "{rev}"\ndown_revision = "{down}"\nbranch_labels = None\ndepends_on = None\n\n\ndef upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n'


def git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout.strip()


def add_revision(repo, rev, down):
    (repo / "alembic" / "versions" / f"{rev}_dev.py").write_text(
        REVISION.format(name=rev, rev=rev, down=down), encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"revision {rev}")


def heads_ok(repo, capsys):
    # 같은 초·같은 길이로 수정한 리비전 파일이 오래된 .pyc 로 읽히지 않게 캐시를 지운다
    shutil.rmtree(repo / "alembic" / "versions" / "__pycache__", ignore_errors=True)
    ok = heads_check.check_heads(repo / "alembic")
    return ok, capsys.readouterr().out


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(
        API_ROOT / "alembic", root / "alembic", ignore=shutil.ignore_patterns("__pycache__")
    )
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    return root


def current_head(repo):
    return heads_check._script_directory(repo / "alembic").get_current_head()


def test_parallel_branches_conflict_only_at_merge_and_are_fixed_by_rebasing_down_revision(
    repo, capsys
):
    base = current_head(repo)
    for name in (
        "dev_a",
        "dev_b",
        "dev_c",
    ):  # 서로 다른 브랜치에서 같은 부모 위에 각자 리비전을 만든다
        git(repo, "switch", "-q", "-c", name, "main")
        add_revision(
            repo,
            {"dev_a": "aaaa00000001", "dev_b": "bbbb00000002", "dev_c": "cccc00000003"}[name],
            base,
        )
        ok, _ = heads_ok(repo, capsys)
        assert ok, f"{name} 은(는) 혼자서는 단일 head 여야 한다"

    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-edit", "dev_a")  # 먼저 병합된 쪽
    assert heads_ok(repo, capsys)[0]

    # dev_b 의 PR merge ref = 최신 main 과 합친 상태 → head 2개 → CI 실패
    git(repo, "switch", "-q", "dev_b")
    git(repo, "merge", "-q", "--no-edit", "main")
    ok, out = heads_ok(repo, capsys)
    assert not ok and "aaaa00000001" in out and "bbbb00000002" in out and "head 가 2개" in out

    # 뒤에 병합되는 쪽이 down_revision 을 main 의 현재 head 로 옮기면 통과
    path = repo / "alembic" / "versions" / "bbbb00000002_dev.py"
    path.write_text(
        re.sub(
            r'down_revision = "\w+"',
            'down_revision = "aaaa00000001"',
            path.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    git(repo, "commit", "-qam", "re-parent bbbb")
    assert heads_ok(repo, capsys)[0] and current_head(repo) == "bbbb00000002"
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-edit", "dev_b")

    # dev_c 도 같은 절차: 병합 결과 head 2개(bbbb, cccc) → 실패 → 재배치 → 통과. 최종은 선형 체인
    git(repo, "switch", "-q", "dev_c")
    git(repo, "merge", "-q", "--no-edit", "main")
    ok, out = heads_ok(repo, capsys)
    assert not ok and "bbbb00000002" in out and "cccc00000003" in out
    path = repo / "alembic" / "versions" / "cccc00000003_dev.py"
    path.write_text(
        re.sub(
            r'down_revision = "\w+"',
            'down_revision = "bbbb00000002"',
            path.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )
    git(repo, "commit", "-qam", "re-parent cccc")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-edit", "dev_c")
    ok, out = heads_ok(repo, capsys)
    assert ok and current_head(repo) == "cccc00000003"


def test_the_real_ci_job_checks_the_pr_merge_result_not_only_the_branch():
    """pull_request 이벤트의 actions/checkout 은 기본으로 PR 을 base(main)와 합친 merge ref 를 받는다 —
    ci-check.yml 이 ref 를 고정하지 않아 단일 head 검사가 '최신 main 기준 병합 결과'에 적용된다."""
    import yaml

    ci = yaml.safe_load(
        (API_ROOT.parents[1] / ".github" / "workflows" / "ci-check.yml").read_text(encoding="utf-8")
    )
    triggers = ci.get("on") or ci.get(True)
    # 수동 전용(workflow_dispatch)으로 바꾼 상태에서는 PR·push 조건을 요구하지 않는다
    assert "workflow_dispatch" in triggers or ("pull_request" in triggers and "push" in triggers)
    for job in ci["jobs"].values():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                assert "ref" not in (step.get("with") or {})
