"""사용자 요청형 추억 생성 시험(PR10): 합성 이미지·가짜 인코더만 쓴다. 입구 가드·동의·자격·중복 요청·진행 상태·실패·철회 경합·가족 격리를 본다."""

import io
import random
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat import photo_check_service as pcs
from app.features.family_chat import photo_service as ps
from app.features.family_memory import analysis, worker
from app.features.family_memory import job_repository as jobs
from app.features.family_memory import job_service as js
from app.features.family_memory.models import (
    FamilyMemoryJob,
    MemoryCandidate,
    MemoryCandidatePhoto,
    PhotoEmbedding,
)
from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.db import SessionLocal

BASE = "/family-memory"
GEN = f"{BASE}/generation"
PHOTOS = "/family-chat/photos"
KIND = analysis.KIND_EMBEDDING
DAY = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
CONFIRM = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}
_n = [0]
_MSG: dict[str, str] = {}  # 사진 id → 메시지 id(실제 삭제 시험용)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    monkeypatch.setattr(settings, "family_memory_generate_enabled", True)
    monkeypatch.setattr(settings, "family_memory_consent_version_required", True)
    monkeypatch.setattr(settings, "family_memory_encoder", "fake")
    saved = dict(worker._handlers)
    hooks = (
        list(memory_hooks._member_withdrawn),
        list(memory_hooks._family_disabled),
        list(memory_hooks._photo_excluded),
        list(memory_hooks._attachment_removed),
    )
    analysis.reset_encoder()
    yield
    analysis.reset_encoder()
    worker._handlers.clear()
    worker._handlers.update(saved)
    memory_hooks._member_withdrawn[:] = hooks[0]
    memory_hooks._family_disabled[:] = hooks[1]
    memory_hooks._photo_excluded[:] = hooks[2]
    memory_hooks._attachment_removed[:] = hooks[3]


def _image() -> bytes:
    _n[0] += 1
    rng = random.Random(_n[0])
    img = Image.new("RGB", (64, 48))
    img.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 48)]
    )
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _gid(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _photo(client, headers, minutes=0, confirm=True, room_id=None, status="unsure", body=None):
    ps.upload_limiter._failures.clear()
    pcs.check_limiter._failures.clear()
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", body or _image(), "image/jpeg")},
        data={
            "taken_at": (DAY + timedelta(minutes=minutes)).isoformat(),
            **({"room_id": room_id} if room_id else {}),
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    _MSG[att] = r.json()["id"]
    if confirm:
        with SessionLocal() as db:
            assert checks.record_auto(db, _gid(client, headers), att, status)
        assert (
            client.post(f"{PHOTOS}/{att}/check", json=CONFIRM, headers=headers).status_code == 200
        )
    return att


def _ready(client, owner, *members):
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=owner).status_code == 200
    for m in members:
        r = client.put(f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=m)
        assert r.status_code == 200, r.text


def _photos(client, headers, n=4):
    return [_photo(client, headers, minutes=i * 5) for i in range(n)]


def _count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _work(n):
    analysis.register_handlers()
    for _ in range(n):
        assert worker.run_once("w1") == "done"


def _post(client, headers):
    r = client.post(GEN, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- 입구 가드·사전 조건 ----------
def test_entry_is_closed_by_default_and_hides_its_existence(client, family, monkeypatch):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a)
    monkeypatch.setattr(settings, "family_memory_generate_enabled", False)  # 기본값
    assert client.get(GEN, headers=a).status_code == 404
    assert client.post(GEN, headers=a).status_code == 404
    assert _count(FamilyMemoryJob) == 0  # 아무 사진도 등록되지 않았다


def test_entry_needs_consent_version_enforcement_so_real_photos_are_not_processed_without_it(
    client, family, monkeypatch
):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a)
    monkeypatch.setattr(settings, "family_memory_consent_version_required", False)
    for call in (client.get, client.post):
        r = call(GEN, headers=a)
        assert r.status_code == 403 and r.json()["code"] == "generation_not_open"
    assert _count(FamilyMemoryJob) == 0


def test_defaults_keep_generation_and_everything_else_off():
    from app.shared.config import Settings

    fresh = Settings(_env_file=None)
    assert fresh.family_memory_generate_enabled is False
    assert fresh.family_memory_enabled is False and fresh.family_memory_worker_enabled is False
    assert fresh.family_memory_candidates_api_enabled is False


def test_request_is_refused_without_server_family_or_own_consent(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    r = client.post(GEN, headers=a)
    assert r.status_code == 403 and r.json()["code"] == "memory_disabled"
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    r = client.post(GEN, headers=a)
    assert r.status_code == 403 and r.json()["code"] == "family_off"
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    r = client.post(GEN, headers=a)  # 가족은 켰지만 요청자 본인이 동의하지 않았다
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    assert client.get(GEN, headers=b).json()["state"] == "needs_consent"  # 동의 전 상태 조회는 가능
    assert _count(FamilyMemoryJob) == 0


def test_unauthenticated_request_is_rejected(client):
    assert client.post(GEN).status_code in (401, 403)


# ---------- 한 번의 요청으로 끝까지 ----------
def test_one_request_enqueues_then_progress_and_candidates_follow_without_duplicates(
    client, family
):
    a, _, _ = family
    _ready(client, a, a)
    atts = set(_photos(client, a))
    first = _post(client, a)
    assert (first["state"], first["eligible"], first["enqueued"], first["processing"]) == (
        "processing",
        4,
        4,
        4,
    )
    assert (
        first["candidates"] == 0 and _count(MemoryCandidate) == 0
    )  # 임베딩 전에는 후보를 만들지 않는다
    assert client.get(GEN, headers=a).json()["state"] == "processing"
    again = _post(client, a)  # 처리 전에 다시 눌러도 중복 등록 없음
    assert (again["enqueued"], again["processing"]) == (0, 4) and _count(FamilyMemoryJob) == 4
    _work(4)
    assert (
        client.get(GEN, headers=a).json()["state"] == "ready"
    )  # 읽기 전용 조회는 후보를 만들지 않는다
    assert _count(MemoryCandidate) == 0
    done = _post(client, a)  # 준비되면 같은 요청이 후보를 새로 계산한다
    assert (done["state"], done["embedded"], done["candidates"], done["processing"]) == (
        "ready",
        4,
        1,
        0,
    )
    for _ in range(3):  # 반복 요청: 분석·카드 모두 그대로
        again = _post(client, a)
        assert (again["state"], again["enqueued"], again["candidates"]) == ("ready", 0, 1)
    assert _count(FamilyMemoryJob) == 4 and _count(PhotoEmbedding) == 4
    assert _count(MemoryCandidate) == 1 and _count(MemoryCandidatePhoto) == 4
    items = client.get(f"{BASE}/candidates", headers=a).json()["items"]
    assert len(items) == 1 and {p["attachment_id"] for p in items[0]["photos"]} == atts
    assert items[0]["status"] == "private"  # 자동 게시 없음
    with SessionLocal() as db:  # 요청이 사진 판별 상태를 바꾸지 않는다(E1 자동 승인 없음)
        from app.features.family_chat.models import ChatPhotoCheck

        assert set(db.scalars(select(ChatPhotoCheck.status))) == {"photo"}


def test_new_photos_are_added_incrementally_without_reanalyzing_old_ones(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 3)
    _post(client, a)
    _work(3)
    assert _post(client, a)["candidates"] == 1
    _photo(client, a, minutes=40)
    step = _post(client, a)
    assert (step["enqueued"], step["state"]) == (1, "processing")  # 새 사진 한 장만
    _work(1)
    final = _post(client, a)
    assert (final["state"], final["embedded"], final["candidates"]) == ("ready", 4, 1)
    assert _count(FamilyMemoryJob) == 4 and _count(PhotoEmbedding) == 4


def test_not_enough_photos_does_not_enqueue(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 2)
    out = _post(client, a)
    assert (out["state"], out["eligible"], out["enqueued"]) == ("not_enough_photos", 2, 0)
    assert _count(FamilyMemoryJob) == 0


def test_request_cap_spreads_registration_over_requests(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "family_memory_generate_max_photos", 3)
    _ready(client, a, a)
    _photos(client, a, 5)
    one = _post(client, a)
    assert (one["enqueued"], one["capped"]) == (3, True)
    two = _post(client, a)
    assert (two["enqueued"], two["capped"]) == (2, False) and _count(FamilyMemoryJob) == 5


# ---------- 자격: 문서·미확인·1:1·제외·소급 ----------
def test_unconfirmed_document_direct_and_excluded_photos_are_never_enqueued(client, family):
    a, b, _ = family
    _ready(client, a, a)
    _photos(client, a, 3)
    _photo(client, a, minutes=30, confirm=False)  # 업로더가 확인하지 않은 사진(D-13)
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, a)}, headers=b
    ).json()
    direct = _photo(client, b, minutes=32, confirm=False, room_id=room["id"])
    excluded = _photo(client, a, minutes=33)
    assert (
        client.put(
            f"{BASE}/photos/{excluded}/exclusion", json={"excluded": True}, headers=a
        ).status_code
        == 200
    )
    out = _post(client, a)
    assert out["eligible"] == 3 and out["enqueued"] == 3  # 확인된 3장만
    with SessionLocal() as db:
        queued = set(db.scalars(select(FamilyMemoryJob.attachment_id)))
    assert direct not in queued and excluded not in queued and len(queued) == 3


def test_a_photo_judged_as_document_is_not_eligible(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 3)
    doc = _photo(client, a, minutes=30, confirm=False)
    with SessionLocal() as db:
        assert checks.record_auto(db, _gid(client, a), doc, "document")
    assert _post(client, a)["eligible"] == 3


def test_other_members_photos_need_their_own_consent(client, family):
    a, b, _ = family
    _ready(client, a, a)  # b 는 동의하지 않았다
    _photos(client, a, 3)
    theirs = [_photo(client, b, minutes=40 + i) for i in range(3)]
    out = _post(client, a)
    assert (out["eligible"], out["enqueued"]) == (3, 3)
    with SessionLocal() as db:
        assert not set(theirs) & set(db.scalars(select(FamilyMemoryJob.attachment_id)))


def test_past_photos_need_retro_consent_and_it_is_never_implied(client, family):
    a, _, _ = family
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    past = _photos(client, a, 4)  # 동의하기 전에 올린 사진
    assert (
        client.put(
            f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=a
        ).status_code
        == 200
    )
    blocked = _post(client, a)
    assert (blocked["eligible"], blocked["enqueued"], blocked["state"]) == (
        0,
        0,
        "not_enough_photos",
    )
    assert _count(FamilyMemoryJob) == 0
    new = [_photo(client, a, minutes=60 + i) for i in range(3)]  # 동의 뒤에 올린 새 사진은 된다
    out = _post(client, a)
    assert out["eligible"] == 3
    with SessionLocal() as db:
        assert set(db.scalars(select(FamilyMemoryJob.attachment_id))) == set(new)
    assert client.put(f"{BASE}/consent/retro", json={"consent": True}, headers=a).status_code == 200
    wide = _post(client, a)  # 소급 동의를 따로 한 뒤에만 과거 사진이 들어온다
    assert wide["eligible"] == 7
    with SessionLocal() as db:
        assert set(db.scalars(select(FamilyMemoryJob.attachment_id))) == set(new) | set(past)


def test_past_photos_never_reach_candidates_without_retro_consent(client, family):
    a, _, _ = family
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    _photos(client, a, 3)  # 과거
    assert (
        client.put(
            f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=a
        ).status_code
        == 200
    )
    new = [_photo(client, a, minutes=60 + i * 5) for i in range(3)]
    _post(client, a)
    _work(3)
    done = _post(client, a)
    assert done["candidates"] == 1
    items = client.get(f"{BASE}/candidates", headers=a).json()["items"]
    assert {p["attachment_id"] for p in items[0]["photos"]} == set(new)


# ---------- 실패·재시도·복구 ----------
def test_worker_failure_retries_then_marks_failed_and_requests_do_not_revive_it(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 3)
    _post(client, a)
    t = datetime.now(UTC)
    with SessionLocal() as db:
        for attempt in range(3):
            for _ in range(3):
                job = js.claim(db, "w1", [KIND], t + timedelta(hours=attempt + 1))
                assert job is not None
                outcome = js.fail(
                    db, job, "w1", "EncoderUnavailable", t + timedelta(hours=attempt + 1)
                )
                assert outcome in ("retry", "failed")
    state = _post(client, a)
    assert (state["state"], state["failed"], state["processing"], state["enqueued"]) == (
        "failed",
        3,
        0,
        0,
    )
    again = _post(client, a)  # 실패한 사진을 요청이 되살리지 않는다(무한 재시도 방지)
    assert (again["state"], again["enqueued"]) == ("failed", 0)
    with SessionLocal() as db:
        assert set(db.scalars(select(FamilyMemoryJob.status))) == {jobs.FAILED}
        assert set(db.scalars(select(FamilyMemoryJob.attempts))) == {3}


def test_gpu_out_of_memory_leaves_the_job_for_retry_and_the_request_keeps_processing(
    client, family
):
    from app.features.family_memory import encoder

    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 3)
    _post(client, a)
    boom = encoder.FakeEncoder(fail_with=encoder.EncoderResourceError("OutOfMemory"))
    analysis._encoder = boom
    analysis.register_handlers()
    assert worker.run_once("w1") == "retry"  # 워커는 죽지 않고 작업을 재시도 대기로 돌린다
    state = client.get(GEN, headers=a).json()
    assert state["state"] == "processing" and state["embedded"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PhotoEmbedding)) == 0


def test_lease_is_at_most_five_minutes_and_an_expired_lease_is_recovered_without_duplicates(
    client, family
):
    a, _, _ = family
    assert settings.family_memory_job_lease_seconds <= 300
    _ready(client, a, a)
    _photos(client, a, 3)
    _post(client, a)
    t0 = datetime.now(UTC)
    with SessionLocal() as db:
        crashed = js.claim(db, "crashed", [KIND], t0)  # 워커가 작업을 잡은 채 죽었다
        assert crashed is not None
    later = t0 + timedelta(seconds=settings.family_memory_job_lease_seconds + 1)
    with SessionLocal() as db:
        assert jobs.recover_expired(db, later) == 1
        db.commit()
    _post(client, a)
    assert _count(FamilyMemoryJob) == 3  # 요청이 다시 와도 작업은 그대로 세 줄
    analysis.register_handlers()
    when = later + timedelta(hours=1)  # 복구된 작업의 재시도 대기가 지난 뒤 새 워커가 이어 받는다
    for _ in range(3):
        with SessionLocal() as db:
            job = js.claim(db, "fresh", [KIND], when)
            assert job is not None
            assert js.complete(db, job, "fresh", analysis.run(job), analysis.save) == "done"
    done = _post(client, a)
    assert (done["state"], done["embedded"], done["candidates"]) == ("ready", 3, 1)
    assert _count(PhotoEmbedding) == 3


# ---------- 철회·삭제 경합, 가족 격리 ----------
def test_withdrawal_after_request_cancels_work_and_blocks_results(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _post(client, a)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    with SessionLocal() as db:
        assert set(db.scalars(select(FamilyMemoryJob.status))) == {jobs.CANCELED}
    state = client.get(GEN, headers=a).json()
    assert state["state"] == "needs_consent" and state["eligible"] == 0
    assert client.post(GEN, headers=a).status_code == 403  # 철회한 사람은 다시 요청할 수 없다
    assert _count(PhotoEmbedding) == 0 and _count(MemoryCandidate) == 0


def test_withdrawal_between_requests_removes_embeddings_and_candidates(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _post(client, a)
    _work(4)
    assert _post(client, a)["candidates"] == 1
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert _count(PhotoEmbedding) == 0 and _count(MemoryCandidate) == 0
    assert client.get(f"{BASE}/candidates", headers=a).json()["items"] == []
    # 재동의해도 이전 사진은 과거 사진이라 소급 동의 없이는 다시 분석되지 않는다
    assert (
        client.put(
            f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=a
        ).status_code
        == 200
    )
    back = _post(client, a)
    assert (back["eligible"], back["enqueued"]) == (0, 0)


def test_deleting_a_photo_after_request_drops_it_from_the_result(client, family):
    a, _, _ = family
    _ready(client, a, a)
    atts = _photos(client, a, 4)
    _post(client, a)
    assert (
        client.delete(f"/family-chat/messages/{_MSG[atts[0]]}", headers=a).status_code == 200
    )  # 실제 메시지 삭제
    state = client.get(GEN, headers=a).json()
    assert state["processing"] == 3  # 지운 사진의 작업은 취소됐다
    _work(3)
    done = _post(client, a)
    assert (done["state"], done["embedded"]) == ("ready", 3)
    ids = {
        p["attachment_id"]
        for p in client.get(f"{BASE}/candidates", headers=a).json()["items"][0]["photos"]
    }
    assert atts[0] not in ids


def test_other_families_are_isolated(client, family, other_family):
    a, _, _ = family
    o = other_family
    _ready(client, a, a)
    _ready(client, o, o)
    mine = _photos(client, a, 4)
    theirs = _photos(client, o, 4)
    out = _post(client, a)
    assert (out["eligible"], out["enqueued"]) == (4, 4)
    with SessionLocal() as db:
        queued = set(db.scalars(select(FamilyMemoryJob.attachment_id)))
    assert queued == set(mine) and not queued & set(theirs)
    assert (
        client.get(GEN, headers=o).json()["state"] == "idle"
    )  # 다른 가족은 아직 아무것도 시작하지 않았다
    _work(4)
    _post(client, a)
    assert client.get(f"{BASE}/candidates", headers=o).json()["items"] == []
    _post(client, o)
    _work(4)
    _post(client, o)
    a_ids = {
        p["attachment_id"]
        for i in client.get(f"{BASE}/candidates", headers=a).json()["items"]
        for p in i["photos"]
    }
    o_ids = {
        p["attachment_id"]
        for i in client.get(f"{BASE}/candidates", headers=o).json()["items"]
        for p in i["photos"]
    }
    assert a_ids == set(mine) and o_ids == set(theirs)


def test_status_endpoint_is_read_only(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    before = (_count(FamilyMemoryJob), _count(MemoryCandidate))
    for _ in range(3):
        assert client.get(GEN, headers=a).json()["state"] == "idle"
    assert (_count(FamilyMemoryJob), _count(MemoryCandidate)) == before == (0, 0)


def test_generation_response_has_only_counts():
    from app.features.family_memory.schemas import GenerationOut

    assert set(GenerationOut.model_fields) == {
        "state", "eligible", "embedded", "processing", "failed", "candidates", "enqueued", "capped",
    }  # fmt: skip


def test_generation_works_end_to_end_with_real_siglip2_embeddings_replayed(client, family):
    """합성 장면 12장의 **실제 SigLIP2 임베딩**(고정 자료, PR9)을 재생하는 인코더로 요청형 생성이 후보까지 가는지 본다. 모델 추론 자체는 이 환경(torch 없음)에서 돌지 않는다."""
    from app.features.family_memory.tests.test_pipeline_real_embeddings import ReplayEncoder
    from tests import synthetic_scenes as scenes

    a, _, _ = family
    analysis._encoder = ReplayEncoder()
    _ready(client, a, a)
    n = 0
    for scene in scenes.SCENES:
        for v in range(scenes.VARIANTS):
            _photo(client, a, minutes=2 * n, body=scenes.jpeg_bytes(scene, v))
            n += 1
    first = _post(client, a)
    assert (first["state"], first["eligible"], first["enqueued"]) == ("processing", 12, 12)
    _work(12)
    done = _post(client, a)
    assert (done["state"], done["embedded"], done["candidates"]) == ("ready", 12, 1)
    with SessionLocal() as db:
        assert set(db.scalars(select(PhotoEmbedding.dim))) == {768}  # 실제 모델의 768차원
    again = _post(client, a)
    assert (again["enqueued"], again["candidates"]) == (0, 1) and _count(MemoryCandidate) == 1
