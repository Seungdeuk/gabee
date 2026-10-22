"""scripts/shared_db_deploy.py 단위 테스트(Docker·DB 없이). 전체 흐름은 test_shared_db_deploy_e2e.py."""

import datetime as dt
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import shared_db_deploy as deploy  # noqa: E402

SHA = "a" * 40
API_ROOT = Path(__file__).resolve().parents[1]


class FakeCi:
    def __init__(self, status="ok", reason=""):
        self.verdict = deploy.CiVerdict(status, reason)
        self.calls = 0

    def verify(self, sha):
        self.calls += 1
        return self.verdict


@pytest.fixture
def dirs(tmp_path):
    pgpass = tmp_path / "pgpass"
    pgpass.write_text("x")
    return {"backup_dir": tmp_path / "backups", "state_dir": tmp_path / "state", "pgpass": pgpass}


def make(dirs, ci=None, target=deploy.SHARED, trusted=(deploy.SHARED,), **kw):
    return deploy.Deployer(
        target=target, trusted_targets=trusted, sha=SHA, ci_verifier=ci or FakeCi(),
        verify_checkout=False, **dirs, **kw,
    )  # fmt: skip


def forbid_connect(monkeypatch):
    def boom(self):
        raise AssertionError("DB 에 연결하면 안 됩니다")

    monkeypatch.setattr(deploy.Deployer, "_connect", boom)


# ---------- 배포 대상 보호 ----------
def test_shared_target_constants_are_exact():
    assert (deploy.SHARED.host, deploy.SHARED.port) == ("192.168.0.44", 5432)
    assert (deploy.SHARED.database, deploy.SHARED.user) == ("gabee", "gabee_migrator")


@pytest.mark.parametrize(
    "target",
    [
        deploy.Target("192.168.0.44", 5432, "family-secretary", "gabee_migrator"),  # MVP DB
        deploy.Target("192.168.0.44", 5432, "gabee", "gabee_app"),  # 앱 계정
        deploy.Target("192.168.0.44", 5432, "gabee", "postgres"),
        deploy.Target("192.168.0.45", 5432, "gabee", "gabee_migrator"),  # 잘못된 주소
        deploy.Target("192.168.0.44", 5433, "gabee", "gabee_migrator"),
        deploy.Target("127.0.0.1", 5433, "gabee", "gabee_migrator"),  # 개인 로컬 DB
    ],
)
def test_wrong_targets_are_refused_before_any_connection(dirs, monkeypatch, target):
    forbid_connect(monkeypatch)
    ci = FakeCi()
    result = make(dirs, ci=ci, target=target).run()
    assert result["outcome"] == "refused"
    assert ci.calls == 0


def test_forbidden_database_is_refused_even_if_listed_as_trusted(dirs, monkeypatch):
    forbid_connect(monkeypatch)
    mvp = deploy.Target("192.168.0.44", 5432, "family-secretary", "gabee_migrator")
    assert make(dirs, target=mvp, trusted=(mvp,)).run()["outcome"] == "refused"


def test_missing_pgpass_is_refused(dirs, monkeypatch):
    forbid_connect(monkeypatch)
    dirs["pgpass"].unlink()
    assert make(dirs).run()["outcome"] == "refused"


# ---------- CI 게이트 ----------
@pytest.mark.parametrize(
    "status,outcome", [("not_green", "blocked"), ("unknown", "blocked"), ("stale", "skipped")]
)
def test_ci_not_ok_stops_before_touching_db(dirs, monkeypatch, status, outcome):
    forbid_connect(monkeypatch)
    result = make(dirs, ci=FakeCi(status, "reason")).run()
    assert result["outcome"] == outcome
    assert not dirs["backup_dir"].exists()


def test_halt_file_blocks_everything(dirs, monkeypatch):
    forbid_connect(monkeypatch)
    dirs["state_dir"].mkdir()
    (dirs["state_dir"] / "HALT").write_text("이전 실패")
    ci = FakeCi()
    result = make(dirs, ci=ci).run()
    assert result["outcome"] == "halted"
    assert ci.calls == 0


def test_cli_has_no_way_to_skip_ci_and_requires_token(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    argv = [
        "run",
        "--sha",
        SHA,
        "--repo",
        "o/r",
        "--backup-dir",
        "b",
        "--state-dir",
        "s",
        "--pgpass",
        "p",
    ]
    assert deploy.main(argv) == 2
    with pytest.raises(SystemExit):
        deploy.main([*argv, "--skip-ci"])
    with pytest.raises(SystemExit):
        deploy.main([*argv, "--profile", "personal"])


# ---------- GitHub CI 검증 로직 ----------
def ci_responses(
    *,
    tip=SHA,
    conclusion="success",
    jobs=None,
    event="push",
    path=".github/workflows/ci-check.yml@refs/heads/main",
    status="completed",
    no_runs=False,
    commit_date="2020-01-01T00:00:00Z",
):
    jobs = jobs or {"api": "success", "api-postgres": "success", "mobile": "success"}
    run = {"id": 9, "run_number": 1, "head_sha": SHA, "head_branch": "main", "event": event, "status": status, "conclusion": conclusion, "path": path, "head_repository": {"full_name": "o/r"}}  # fmt: skip

    def fetch(url):
        if "/branches/main" in url:
            return {"commit": {"sha": tip}}
        if "/actions/runs?" in url:
            return {"workflow_runs": [] if no_runs else [run]}
        if "/commits/" in url:
            return {"commit": {"committer": {"date": commit_date}}}
        if "/jobs" in url:
            return {"jobs": [{"name": n, "conclusion": c} for n, c in jobs.items()]}
        raise AssertionError(url)

    return fetch


def verdict(**kw):
    return deploy.GitHubCiVerifier("o/r", "t", fetch=ci_responses(**kw)).verify(SHA)


def test_ci_verifier_waits_while_ci_is_running_or_not_started_yet():
    assert verdict(status="in_progress", conclusion=None).status == "pending"
    assert verdict(status="queued", conclusion=None).status == "pending"
    recent = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert (
        verdict(no_runs=True, commit_date=recent).status == "pending"
    )  # 병합 직후, 실행이 아직 안 보임
    assert (
        verdict(no_runs=True).status == "not_green"
    )  # 오래된 커밋인데 CI 실행이 없으면 대기가 아니라 실패


def test_deployer_treats_pending_ci_as_skipped_not_failure(dirs, monkeypatch):
    forbid_connect(monkeypatch)
    result = make(dirs, ci=FakeCi("pending", "CI 진행 중")).run()
    assert result["outcome"] == "skipped"


def test_github_api_address_can_only_be_github_or_loopback(monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", "https://evil.example.com")
    with pytest.raises(deploy.Refused):
        deploy.api_base()
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9999")
    assert deploy.api_base() == "http://127.0.0.1:9999"
    monkeypatch.delenv("GITHUB_API_URL")
    assert deploy.api_base() == "https://api.github.com"


def test_loopback_target_override_never_points_at_the_real_shared_host(monkeypatch):
    monkeypatch.delenv("GABEE_DEPLOY_LOOPBACK_TARGET", raising=False)
    assert deploy.target_from_env() == deploy.SHARED
    monkeypatch.setenv("GABEE_DEPLOY_LOOPBACK_TARGET", "192.168.0.44,5432,gabee,gabee_migrator,,0,")
    with pytest.raises(deploy.Refused):
        deploy.target_from_env()
    monkeypatch.setenv(
        "GABEE_DEPLOY_LOOPBACK_TARGET", "127.0.0.1,5555,gabee,gabee_migrator,db,5432,net"
    )
    assert deploy.target_from_env() == deploy.Target(
        "127.0.0.1", 5555, "gabee", "gabee_migrator", "db", 5432, "net"
    )


def test_ci_verifier_accepts_fully_green_commit():
    assert verdict().status == "ok"


def test_ci_verifier_rejects_failed_job_even_if_run_looks_ok():
    assert (
        verdict(jobs={"api": "success", "api-postgres": "failure", "mobile": "success"}).status
        == "not_green"
    )


def test_ci_verifier_rejects_missing_required_job():
    assert verdict(jobs={"api": "success", "mobile": "success"}).status == "not_green"


def test_ci_verifier_rejects_failed_run_and_other_workflow_or_event():
    assert verdict(conclusion="failure").status == "not_green"
    assert verdict(path=".github/workflows/other.yml@refs/heads/main").status == "not_green"
    assert verdict(event="pull_request").status == "not_green"


def test_ci_verifier_detects_main_moving_on():
    assert verdict(tip="b" * 40).status == "stale"


def test_ci_verifier_network_error_is_unknown_not_ok():
    def fetch(url):
        raise TimeoutError

    assert deploy.GitHubCiVerifier("o/r", "t", fetch=fetch).verify(SHA).status == "unknown"


# ---------- Alembic 분석 ----------
def alembic_copy(tmp_path, extra: dict[str, str] | None = None) -> Path:
    dest = tmp_path / "alembic"
    shutil.copytree(API_ROOT / "alembic", dest, ignore=shutil.ignore_patterns("__pycache__"))
    for name, text in (extra or {}).items():
        (dest / "versions" / name).write_text(text, encoding="utf-8")
    return dest


def revision(rev, down, body="pass", doc="test"):
    return f'"""{doc}"""\nfrom alembic import op\nimport sqlalchemy as sa\nrevision = "{rev}"\ndown_revision = "{down}"\nbranch_labels = None\ndepends_on = None\n\n\ndef upgrade():\n    {body}\n\n\ndef downgrade():\n    pass\n'


def head_rev():
    return deploy.Deployer(target=deploy.SHARED, trusted_targets=(), sha=SHA, backup_dir=Path("b"), state_dir=Path("s"), pgpass=Path("p"), ci_verifier=FakeCi())._script().get_current_head()  # fmt: skip


def test_analyze_noop_when_db_is_at_head(dirs):
    d = make(dirs)
    head, pending = d._analyze(d._script(), head_rev())
    assert (head, pending) == (head_rev(), [])


def test_analyze_lists_pending_in_order_without_current(dirs):
    d = make(dirs)
    head, pending = d._analyze(d._script(), "355a1a748ec5")
    chain = [r.revision for r in d._script().iterate_revisions(head, "355a1a748ec5")]
    expected = [r for r in chain if r != "355a1a748ec5"][
        ::-1
    ]  # main 에 리비전이 늘어도 맞도록 코드에서 계산
    assert [r.revision for r in pending] == expected
    assert expected[:2] == ["9e28d84c1686", "b6931fc30c66"] and expected[-1] == head


def test_multiple_heads_are_blocked(dirs, tmp_path):
    ad = alembic_copy(tmp_path, {"c1_branch.py": revision("c1", "9e28d84c1686")})
    d = make(dirs, alembic_dir=ad)
    with pytest.raises(deploy.Failure) as exc:
        d._analyze(d._script(), "355a1a748ec5")
    assert exc.value.outcome == "blocked" and "head" in exc.value.message


def test_db_revision_unknown_to_code_is_blocked(dirs):
    d = make(dirs)
    with pytest.raises(deploy.Failure) as exc:
        d._analyze(d._script(), "ffffffffffff")
    assert "코드 이력에 없" in exc.value.message


def test_destructive_pending_migration_is_blocked_unless_approved(dirs, tmp_path):
    bad = revision("d1", head_rev(), 'op.drop_column("users", "name")')
    d = make(dirs, alembic_dir=alembic_copy(tmp_path, {"d1_drop.py": bad}))
    _, pending = d._analyze(d._script(), head_rev())
    with pytest.raises(deploy.Failure) as exc:
        d._risk_scan(pending)
    assert exc.value.outcome == "blocked" and "drop_column" in exc.value.message

    ok = revision(
        "d1",
        head_rev(),
        'op.drop_column("users", "name")',
        doc="drop\n\ndestructive-approved: PR #77",
    )
    d2 = make(dirs, alembic_dir=alembic_copy(tmp_path / "ok", {"d1_drop.py": ok}))
    _, pending = d2._analyze(d2._script(), head_rev())
    d2._risk_scan(pending)  # 예외 없음


# ---------- 백업 보관 ----------
def test_retention_keeps_newest_and_never_touches_other_files(dirs):
    backups = dirs["backup_dir"]
    backups.mkdir()
    original = backups / "gabee_pg16.dump"  # 기존 수동 백업
    original.write_bytes(b"original")
    names = [f"gabee_pg16_deploy_2026102{i}T000000Z_aaaa-to-bbbb.dump" for i in range(5)]
    for n in names:
        (backups / n).write_bytes(b"x" * 10)
        (backups / f"{n}.sha256").write_text("h")
    (backups / "notes.txt").write_text("keep")
    d = make(dirs, retention=2)
    d._apply_retention(backups / names[-1])
    remaining = sorted(p.name for p in backups.iterdir())
    assert original.read_bytes() == b"original" and "notes.txt" in remaining
    assert [n for n in remaining if n.endswith(".dump") and "deploy" in n] == names[-2:]
    assert not [n for n in remaining if n.startswith("gabee_pg16_deploy_20261020")]


# ---------- 알림(팀원에게 상태 표시) ----------
def recording_api(open_issues):
    calls = []

    def api(method, path, payload, ok_codes=(200, 201)):
        calls.append((method, path.split("?")[0], payload))
        return open_issues if method == "GET" else None

    return calls, api


FAIL = {"outcome": "blocked", "message": "m", "sha": SHA, "from": "a", "to": "b", "backup": None}


def test_notify_creates_issue_when_none_open():
    calls, api = recording_api([])
    deploy.notify(FAIL, "o/r", "t", "url", fetch=api)
    assert ("POST", "/repos/o/r/issues") in [(m, p) for m, p, _ in calls]


def test_notify_comments_on_existing_open_issue_instead_of_duplicating():
    calls, api = recording_api([{"number": 5}])
    deploy.notify(FAIL, "o/r", "t", "url", fetch=api)
    paths = [(m, p) for m, p, _ in calls]
    assert ("POST", "/repos/o/r/issues/5/comments") in paths and (
        "POST",
        "/repos/o/r/issues",
    ) not in paths


@pytest.mark.parametrize("outcome", ["success", "noop"])
def test_notify_closes_open_failure_issues_when_deploy_recovers(outcome):
    calls, api = recording_api([{"number": 5}, {"number": 6}])
    deploy.notify({**FAIL, "outcome": outcome}, "o/r", "t", "url", fetch=api)
    patched = [(p, payload) for m, p, payload in calls if m == "PATCH"]
    assert patched == [
        ("/repos/o/r/issues/5", {"state": "closed"}),
        ("/repos/o/r/issues/6", {"state": "closed"}),
    ]


@pytest.mark.parametrize("outcome", ["skipped", "halted", "dry_run_ok", "refused"])
def test_notify_ignores_other_outcomes(outcome):
    deploy.notify(
        {**FAIL, "outcome": outcome},
        "o/r",
        "t",
        "url",
        fetch=lambda *a, **k: pytest.fail("호출되면 안 됨"),
    )


# ---------- 공용 DB 보호: 테스트 중 실제 공용 DB 로 접속 시도가 있으면 즉시 실패 ----------
@pytest.fixture(autouse=True)
def never_connect_to_real_shared_db(monkeypatch):
    real_connect = deploy.psycopg.connect

    def guarded(*args, **kwargs):
        if kwargs.get("host") == deploy.SHARED.host:
            raise AssertionError("테스트가 실제 공용 DB 로 접속하려 했습니다")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(deploy.psycopg, "connect", guarded)


# ---------- 배포 대상 커밋 = 검증된 커밋 ----------
def git(repo, *args):
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("1")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "c1")
    return repo


def test_checkout_must_be_exactly_the_verified_commit(dirs, git_repo):
    sha = git(git_repo, "rev-parse", "HEAD")
    d = deploy.Deployer(target=deploy.SHARED, trusted_targets=(deploy.SHARED,), sha=sha, ci_verifier=FakeCi(), api_root=git_repo, **dirs)  # fmt: skip
    d._checkout_ok()  # 같은 커밋·깨끗한 작업 트리: 통과

    (git_repo / "a.txt").write_text("changed")  # 검증되지 않은 로컬 변경
    with pytest.raises(deploy.Failure, match="체크아웃이 검증된 커밋과 다릅니다"):
        d._checkout_ok()
    git(git_repo, "checkout", "--", "a.txt")

    (git_repo / "a.txt").write_text("2")
    git(git_repo, "commit", "-qam", "c2")  # HEAD 가 검증된 커밋(c1)이 아님
    with pytest.raises(deploy.Failure, match="체크아웃이 검증된 커밋과 다릅니다"):
        d._checkout_ok()


def test_ci_run_must_belong_to_the_same_sha():
    def fetch(url):
        if "/branches/main" in url:
            return {"commit": {"sha": SHA}}
        if "/actions/runs?" in url:
            run = {"id": 1, "run_number": 1, "head_sha": "d" * 40, "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success", "path": ".github/workflows/ci-check.yml@refs/heads/main", "head_repository": {"full_name": "o/r"}}  # fmt: skip
            return {"workflow_runs": [run]}
        if "/commits/" in url:
            return {"commit": {"committer": {"date": "2020-01-01T00:00:00Z"}}}
        raise AssertionError(url)

    assert deploy.GitHubCiVerifier("o/r", "t", fetch=fetch).verify(SHA).status == "not_green"


# ---------- 리허설 = 적용 (동일 리비전) ----------
def test_revision_files_changed_after_rehearsal_are_rejected(dirs, tmp_path):
    ad = alembic_copy(tmp_path)
    d = make(dirs, alembic_dir=ad)
    _, pending = d._analyze(d._script(), "b6931fc30c66")
    plan, fingerprint = [r.revision for r in pending], d._revision_fingerprint()
    target = ad / "versions" / "6304cb91e46a_billing_settled_and_manager.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# 리허설 뒤 수정\n", encoding="utf-8")
    with pytest.raises(deploy.Failure, match="리비전 파일이 바뀌어"):
        d._assert_same_as_rehearsed(None, "b6931fc30c66", head_rev(), plan, fingerprint)


def test_pending_set_changed_after_rehearsal_is_rejected(dirs, tmp_path):
    ad = alembic_copy(tmp_path)
    d = make(dirs, alembic_dir=ad)
    _, pending = d._analyze(d._script(), "b6931fc30c66")
    plan, fingerprint = [r.revision for r in pending], d._revision_fingerprint()
    # 같은 파일 해시지만 계획(plan)이 다른 경우: 계획 목록 불일치도 거부
    with pytest.raises(deploy.Failure, match="적용 예정 리비전이 바뀌어"):
        d._assert_same_as_rehearsed(None, "b6931fc30c66", head_rev(), plan[:-1], fingerprint)
