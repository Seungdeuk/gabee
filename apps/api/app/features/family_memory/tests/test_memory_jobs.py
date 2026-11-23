"""AI 추억 분석 작업 큐(PR3): 중복 방지, 선점·임대 복구, 재시도 상한·backoff, 자격 재확인 4지점, 철회·삭제·제외·가족 끄기·나가기 차단, 가족 격리, 1:1 제외, D-13.
이미지 분석은 없다(PR4). 처리 함수는 시험이 등록한 가짜다. `FOR UPDATE SKIP LOCKED` 의 동시 선점은 SQLite 가 보지 못하므로 PostgreSQL e2e(`tests/test_family_memory_pg_e2e.py`)가 본다."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_memory import job_repository as jobs
from app.features.family_memory import job_service as js
from app.features.family_memory import worker
from app.features.family_memory.models import FamilyMemoryJob
from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.db import SessionLocal

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
LEAVE = "/family-group/groups/me/leave"
KINDS = [js.KIND_PHOTO]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    saved = dict(worker._handlers)
    yield
    worker._handlers.clear()
    worker._handlers.update(saved)


def _photo(client, headers, room_id=None):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _confirm(attachment_id, status="photo"):
    """업로더가 일반 사진으로 확인한 상태를 시험용으로 만든다(D-13: 자동 판별은 photo 를 못 만든다)."""
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == attachment_id)
            .values(status=status)
        )
        db.commit()


def _ready(client, owner, uploader):
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=uploader).status_code == 200
    )


def _eligible_photo(client, a):
    """가족 활성화·업로더 동의·확인된 일반 사진까지 갖춘 사진 하나."""
    _ready(client, a, a)
    att, msg = _photo(client, a)
    _confirm(att)
    return att, msg


def _enqueue(att, **kw):
    with SessionLocal() as db:
        return js.enqueue(db, att, **kw)


def _job(att):
    with SessionLocal() as db:
        return jobs.get_by_attachment(db, att, js.KIND_PHOTO)


def _claim(worker_id="w1", now=None):
    with SessionLocal() as db:
        return js.claim(db, worker_id, KINDS, now)


def _count():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(FamilyMemoryJob))


# ---------- ① 등록: 자격·중복 ----------
def test_enqueue_creates_one_queued_job_for_an_eligible_photo(client, family):
    a, _, group = family
    att, _ = _eligible_photo(client, a)
    r = _enqueue(att)
    assert r.outcome == "queued" and r.job_id
    job = _job(att)
    assert (job.status, job.attempts, job.group_id, job.kind) == (
        "queued",
        0,
        group["id"],
        js.KIND_PHOTO,
    )
    assert job.max_attempts == js.MAX_ATTEMPTS


def test_enqueue_is_refused_for_each_ineligible_reason_and_creates_nothing(
    client, family, monkeypatch
):
    a, b, _ = family
    # 가족 비활성·미동의
    att0, _ = _photo(client, a)
    _confirm(att0)
    assert _enqueue(att0).reason == "family_off"
    _ready(client, a, a)
    # 확인되지 않은 사진(pending·unsure·failed·document)은 D-13 으로 자동 승격 없이 거절
    for status in ("pending", "unsure", "failed", "document"):
        att, _ = _photo(client, a)
        _confirm(att, status)
        assert _enqueue(att).reason == "not_confirmed_photo"
    # 사진별 제외
    att_x, _ = _photo(client, a)
    _confirm(att_x)
    assert (
        client.put(
            f"{BASE}/photos/{att_x}/exclusion", json={"excluded": True}, headers=a
        ).status_code
        == 200
    )
    assert _enqueue(att_x).reason == "excluded"
    # 올린 사람이 동의하지 않은 가족 구성원의 사진
    att_b, _ = _photo(client, b)
    _confirm(att_b)
    assert _enqueue(att_b).reason == "no_consent"
    # 서버 스위치 꺼짐
    att_ok, _ = _photo(client, a)
    _confirm(att_ok)
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    assert _enqueue(att_ok).reason == "server_off"
    # 없는 사진
    assert _enqueue("nosuchattach").outcome == "rejected"
    assert _count() == 0


def test_a_one_to_one_photo_is_never_enqueued(client, family):
    a, b, _ = family
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    _ready(client, a, a)
    att, _ = _photo(client, a, room_id=room["id"])
    r = _enqueue(att)
    assert r.outcome == "rejected" and _count() == 0


def test_the_same_photo_is_registered_only_once(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    first, second = _enqueue(att), _enqueue(att)
    assert (first.outcome, second.outcome) == ("queued", "exists")
    assert first.job_id == second.job_id and _count() == 1


def test_a_canceled_job_is_revived_but_a_failed_one_is_not(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    with SessionLocal() as db:
        jobs.cancel_for_attachment(db, att, "excluded", datetime.now(UTC))
        db.commit()
    assert _job(att).status == "canceled"
    assert _enqueue(att).outcome == "requeued"
    j = _job(att)
    assert (j.status, j.attempts, j.cancel_reason) == ("queued", 0, None)
    with SessionLocal() as db:
        db.execute(
            update(FamilyMemoryJob).where(FamilyMemoryJob.id == j.id).values(status="failed")
        )
        db.commit()
    assert (
        _enqueue(att).outcome == "exists" and _job(att).status == "failed"
    )  # 상한에 걸린 작업은 되살리지 않는다


# ---------- ② 선점·임대 복구 ----------
def test_claim_takes_a_job_once_and_counts_the_attempt(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    job = _claim("w1")
    assert job is not None and job.attachment_id == att and job.attempts == 1
    assert _claim("w2") is None  # 다른 워커는 같은 작업을 가져가지 못한다
    row = _job(att)
    assert (row.status, row.locked_by, row.lease_until is not None) == ("running", "w1", True)


def test_claim_only_takes_registered_kinds_and_future_jobs_wait(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    with SessionLocal() as db:
        assert js.claim(db, "w1", ["other_kind"]) is None and js.claim(db, "w1", []) is None
    with SessionLocal() as db:
        db.execute(update(FamilyMemoryJob).values(run_after=datetime.now(UTC) + timedelta(hours=1)))
        db.commit()
    assert _claim() is None  # backoff 중인 작업은 아직 안 가져간다


def test_an_expired_lease_is_recovered_with_backoff_and_a_late_worker_loses(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    t0 = datetime.now(UTC)
    first = _claim("w1", t0)
    later = t0 + timedelta(seconds=settings.family_memory_job_lease_seconds + 1)
    assert _claim("w2", later) is None  # 되찾았지만 backoff(30초) 동안은 대기
    assert (_job(att).status, _job(att).last_error) == ("queued", "lease_expired")
    again = _claim("w2", later + timedelta(seconds=31))
    assert again is not None and again.attempts == 2 and again.id == first.id
    with SessionLocal() as db:  # 느려서 임대를 잃은 첫 워커의 결과는 저장되지 않는다
        assert (
            js.complete(db, first, "w1", save=lambda *a: pytest.fail("저장되면 안 된다")) == "lost"
        )
        assert js.fail(db, first, "w1", "X") == "lost"
    assert _job(att).locked_by == "w2"


def test_recovery_after_a_server_restart_gives_up_at_the_attempt_limit(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    now = datetime.now(UTC)
    for n in range(1, js.MAX_ATTEMPTS + 1):  # 서버가 재시작될 때마다 워커가 중단된 것으로 본다
        job = _claim(f"w{n}", now)
        assert job is not None and job.attempts == n
        now += timedelta(seconds=settings.family_memory_job_lease_seconds + 1)
        with SessionLocal() as db:
            jobs.recover_expired(db, now)
            db.commit()
        now += jobs.BACKOFF_CAP
    row = _job(att)
    assert (row.status, row.attempts, row.last_error) == (
        "failed",
        js.MAX_ATTEMPTS,
        "lease_expired",
    )
    assert _claim("wx", now) is None  # 다시 돌리지 않는다(무한 반복 없음)


# ---------- 재시도 상한·backoff ----------
def test_failures_back_off_then_stop_at_the_limit(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    now = datetime.now(UTC)
    waits = []
    for n in range(1, js.MAX_ATTEMPTS + 1):
        job = _claim("w1", now)
        assert job is not None and job.attempts == n
        with SessionLocal() as db:
            outcome = js.fail(db, job, "w1", "ValueError", now)
        row = _job(att)
        if n < js.MAX_ATTEMPTS:
            assert outcome == "retry" and row.status == "queued"
            waits.append((row.run_after.replace(tzinfo=UTC) - now).total_seconds())
            assert _claim("w1", now) is None  # 대기 시간 전에는 못 가져간다
            now = row.run_after.replace(tzinfo=UTC)
        else:
            assert outcome == "failed" and row.status == "failed" and row.finished_at is not None
    assert waits == [30, 60] and row.last_error == "ValueError"
    assert _claim("w1", now + timedelta(days=1)) is None


def test_backoff_is_capped():
    assert jobs.backoff(1).total_seconds() == 30 and jobs.backoff(20) == jobs.BACKOFF_CAP


# ---------- ③④ 실행·저장 직전 자격 재확인 ----------
def test_complete_saves_the_result_only_while_still_eligible(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    job = _claim("w1")
    saved = []
    with SessionLocal() as db:
        assert js.still_allowed(db, job, "w1") is True
    with SessionLocal() as db:
        assert js.complete(db, job, "w1", {"x": 1}, lambda db, j, r: saved.append(r)) == "done"
    assert saved == [{"x": 1}] and _job(att).status == "done"
    with SessionLocal() as db:
        assert js.complete(db, job, "w1") == "lost"  # 끝난 작업을 다시 끝낼 수 없다


@pytest.mark.parametrize("cause", ["withdraw", "exclude", "family_off", "downgrade_photo"])
def test_losing_eligibility_between_claim_and_save_discards_the_result(client, family, cause):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    job = _claim("w1")
    if cause == "withdraw":  # 훅이 막기 전에 직접 상태만 바뀐 경우도 ④에서 막힌다
        with SessionLocal() as db:
            from app.features.family_memory.models import MemberMemoryConsent

            db.get(MemberMemoryConsent, (job.group_id, job.user_id)).withdrawn_at = datetime.now(
                UTC
            )
            db.commit()
        expected = "no_consent"
    elif cause == "exclude":
        with SessionLocal() as db:
            from app.features.family_memory.models import PhotoAnalysisExclusion

            db.add(
                PhotoAnalysisExclusion(
                    attachment_id=att, group_id=job.group_id, user_id=job.user_id
                )
            )
            db.commit()
        expected = "excluded"
    elif cause == "family_off":
        with SessionLocal() as db:
            from app.features.family_memory.models import FamilyMemorySetting

            db.get(FamilyMemorySetting, job.group_id).enabled = False
            db.commit()
        expected = "family_off"
    else:
        _confirm(att, "unsure")
        expected = "not_confirmed_photo"
    with SessionLocal() as db:
        assert js.still_allowed(db, job, "w1") is False
    row = _job(att)
    assert (row.status, row.cancel_reason) == ("canceled", expected)
    with SessionLocal() as db:
        assert js.complete(db, job, "w1", save=lambda *a: pytest.fail("저장되면 안 된다")) == "lost"


def test_result_is_discarded_when_eligibility_is_lost_just_before_saving(client, family):
    """실행은 자격이 있을 때 시작됐고 저장 직전에 자격을 잃었다: 저장 함수는 불리지 않고 작업은 canceled."""
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    job = _claim("w1")
    with SessionLocal() as db:
        assert js.still_allowed(db, job, "w1")
    client.put(
        f"{BASE}/consent", json={"consent": False}, headers=a
    )  # 실행 중에 철회(훅이 작업을 막는다)
    with SessionLocal() as db:
        assert js.complete(db, job, "w1", save=lambda *a: pytest.fail("저장되면 안 된다")) == "lost"
    assert _job(att).status == "canceled"


def test_claim_skips_and_cancels_jobs_that_lost_eligibility_while_queued(client, family):
    a, _, _ = family
    first, _ = _eligible_photo(client, a)
    second, _ = _photo(client, a)
    _confirm(second)
    _enqueue(first)
    _enqueue(second)
    _confirm(first, "document")  # 대기 중에 문서로 바뀌었다(훅이 없는 경로: ②에서 막힌다)
    job = _claim("w1")
    assert job is not None and job.attachment_id == second
    assert (_job(first).status, _job(first).cancel_reason) == ("canceled", "not_confirmed_photo")


# ---------- 철회·나가기·끄기·제외·삭제 훅 ----------
def test_withdrawal_blocks_queued_and_running_jobs_immediately(client, family):
    a, _, _ = family
    queued, _ = _eligible_photo(client, a)
    running, _ = _photo(client, a)
    _confirm(running)
    _enqueue(queued)
    _enqueue(running)
    _claim("w1")  # 먼저 만든 것이 running
    assert {_job(queued).status, _job(running).status} == {"queued", "running"}
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert {_job(queued).status, _job(running).status} == {"canceled"}
    assert {_job(queued).cancel_reason, _job(running).cancel_reason} == {"withdrawn"}
    assert _claim("w2") is None and _enqueue(queued).reason == "no_consent"


def test_re_consent_after_withdrawal_allows_the_same_photo_to_be_enqueued_again(client, family):
    """철회로 막힌(canceled) 작업은 재동의 뒤 같은 사진으로 다시 등록된다(횟수 0부터). 재동의 전에는 거절된다."""
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert _job(att).status == "canceled" and _enqueue(att).reason == "no_consent"
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    r = _enqueue(att)
    assert r.outcome == "requeued" and r.job_id == _job(att).id
    row = _job(att)
    assert (row.status, row.attempts, row.cancel_reason, row.locked_by) == ("queued", 0, None, None)
    assert _claim("w1") is not None and _count() == 1  # 새 줄이 아니라 같은 줄을 되살린다


def test_default_lease_is_300_seconds_so_a_slow_worker_loses_its_job(client, family):
    """처리 함수는 임대(기본 300초) 안에 끝나야 한다: 넘기면 다른 워커가 되찾고 늦은 워커의 결과는 저장되지 않는다."""
    assert settings.family_memory_job_lease_seconds == 300
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    t0 = datetime.now(UTC)
    job = _claim("slow", t0)
    assert _job(att).lease_until.replace(tzinfo=UTC) == t0 + timedelta(seconds=300)
    with SessionLocal() as db:  # 임대 직전까지는 아직 이 워커의 것
        jobs.recover_expired(db, t0 + timedelta(seconds=299))
        db.commit()
    assert _job(att).locked_by == "slow"
    with SessionLocal() as db:
        jobs.recover_expired(db, t0 + timedelta(seconds=301))
        db.commit()
        assert (
            js.complete(db, job, "slow", save=lambda *a: pytest.fail("저장되면 안 된다")) == "lost"
        )


def test_leaving_the_family_blocks_only_that_members_jobs(client, family):
    a, b, _ = family
    _ready(client, a, a)
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=b).status_code == 200
    mine, _ = _photo(client, a)
    theirs, _ = _photo(client, b)
    _confirm(mine)
    _confirm(theirs)
    _enqueue(mine)
    _enqueue(theirs)
    assert client.post(LEAVE, headers=b).status_code == 204
    assert (_job(theirs).status, _job(theirs).cancel_reason) == ("canceled", "withdrawn")
    assert _job(mine).status == "queued"  # 다른 구성원의 작업은 그대로


def test_turning_the_family_feature_off_blocks_the_whole_familys_jobs(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    assert (_job(att).status, _job(att).cancel_reason) == ("canceled", "family_off")


def test_excluding_a_photo_blocks_its_job_and_nothing_else(client, family):
    a, _, _ = family
    x, _ = _eligible_photo(client, a)
    y, _ = _photo(client, a)
    _confirm(y)
    _enqueue(x)
    _enqueue(y)
    assert (
        client.put(f"{BASE}/photos/{x}/exclusion", json={"excluded": True}, headers=a).status_code
        == 200
    )
    assert (_job(x).status, _job(x).cancel_reason) == ("canceled", "excluded")
    assert _job(y).status == "queued"


def test_deleting_the_photo_removes_its_job_and_a_running_worker_loses(client, family):
    a, _, _ = family
    att, msg = _eligible_photo(client, a)
    _enqueue(att)
    job = _claim("w1")
    assert client.delete(f"{MSG}/{msg}", headers=a).status_code == 200
    assert _job(att) is None and _count() == 0
    with SessionLocal() as db:
        assert js.complete(db, job, "w1", save=lambda *a: pytest.fail("저장되면 안 된다")) == "lost"


def test_a_failing_cancel_hook_does_not_block_the_withdrawal_and_the_gates_still_close_the_job(
    client, family, monkeypatch
):
    """PR6: 작업 차단 훅이 실패해도 철회는 수락된다(동의가 다시 켜진 채 남지 않는다). 못 막은 대기 작업은 선점 때 자격 재확인(②)이 막는다."""
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(jobs, "cancel_for_user", boom)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is False
    assert _job(att).status == "queued"  # 훅은 실패해 작업이 그대로 남았지만
    assert _claim("w1") is None  # 선점 때 자격 재확인이 막는다
    assert (_job(att).status, _job(att).cancel_reason) == ("canceled", "no_consent")


# ---------- 가족 격리 ----------
def test_claim_and_hooks_never_cross_families(client, family, other_family):
    a, _, group = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=other_family).status_code
        == 200
    )
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=other_family).status_code
        == 200
    )
    other_att, _ = _photo(client, other_family)
    _confirm(other_att)
    _enqueue(other_att)
    assert (
        client.put(f"{BASE}/consent", json={"consent": False}, headers=other_family).status_code
        == 200
    )
    assert _job(other_att).status == "canceled" and _job(att).status == "queued"
    with SessionLocal() as db:
        assert jobs.counts(db, group["id"]) == {"queued": 1}


# ---------- 워커 ----------
def test_worker_runs_a_registered_handler_end_to_end_and_saves_through_the_gate(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    saved = []
    worker.register_handler(
        js.KIND_PHOTO, lambda job: {"att": job.attachment_id}, lambda db, job, r: saved.append(r)
    )
    assert worker.run_once("w1") == "done"
    assert saved == [{"att": att}] and _job(att).status == "done"
    assert worker.run_once("w1") is None  # 할 일이 없다


def test_worker_without_handlers_claims_nothing(client, family):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    worker._handlers.clear()
    assert worker.run_once("w1") is None and _job(att).status == "queued"


def test_a_failing_handler_retries_with_backoff_and_logs_only_the_error_kind(
    client, family, caplog
):
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)

    def boom(job):
        raise ValueError("라벨: 비밀 사진 설명 /chat_photos/secret.jpg")

    worker.register_handler(js.KIND_PHOTO, boom)
    with caplog.at_level("INFO"):
        assert worker.run_once("w1") == "retry"
    row = _job(att)
    assert (row.status, row.attempts, row.last_error) == ("queued", 1, "ValueError")
    text = caplog.text + (row.last_error or "") + (row.cancel_reason or "")
    assert "비밀" not in text and "secret" not in text and "chat_photos" not in text


def test_worker_is_off_by_default_and_start_does_nothing(monkeypatch):
    assert settings.family_memory_worker_enabled is False
    assert worker.start() is False
    monkeypatch.setattr(settings, "family_memory_worker_enabled", True)
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    assert worker.start() is False  # 서버 스위치가 꺼져 있으면 시작하지 않는다


def test_d13_job_results_never_change_the_photo_check_state(client, family):
    """작업 큐는 chat_photo_checks 를 읽기만 한다: 어떤 종료 경로도 상태를 바꾸지 않는다."""
    a, _, _ = family
    att, _ = _eligible_photo(client, a)
    _enqueue(att)
    worker.register_handler(js.KIND_PHOTO, lambda job: None)
    worker.run_once("w1")
    with SessionLocal() as db:
        assert (
            db.scalar(select(ChatPhotoCheck.status).where(ChatPhotoCheck.attachment_id == att))
            == "photo"
        )
    pending, _ = _photo(client, a)  # 자동 판별 전(pending)은 등록 자체가 거절된다
    assert _enqueue(pending).reason == "not_confirmed_photo"


def test_hook_registration_is_idempotent_and_survives_the_isolation_fixture():
    before = len(memory_hooks._photo_excluded)
    memory_hooks.register_photo_excluded(js._on_photo_excluded)
    assert len(memory_hooks._photo_excluded) == before >= 1
