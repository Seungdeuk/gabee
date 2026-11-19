"""AI 추억 이미지 임베딩(PR4): 인코더(차원·정규화·재현성·검증·초기화 실패·OOM), 워커 연동(가짜 인코더), 자격 4지점 재확인과 저장 차단, 파생 결과 정리.
모델 파일 없이 돌아간다(가짜 인코더). 실제 SigLIP2 는 `scripts/siglip2_smoke.py` 가 승인된 로컬 파일로 따로 확인한다. 사진은 합성 이미지뿐이다."""

import io
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_memory import analysis, encoder, worker, worker_main
from app.features.family_memory import embedding_repository as emb
from app.features.family_memory import job_repository as jobs
from app.features.family_memory import job_service as js
from app.features.family_memory.models import FamilyMemoryJob, PhotoEmbedding
from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.db import SessionLocal

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
LEAVE = "/family-group/groups/me/leave"
KIND = analysis.KIND_EMBEDDING


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    monkeypatch.setattr(settings, "family_memory_encoder", "fake")
    saved = dict(worker._handlers)
    analysis.reset_encoder()
    yield
    analysis.reset_encoder()
    worker._handlers.clear()
    worker._handlers.update(saved)


def _jpeg(color=(200, 30, 30), size=(64, 48), gradient=True) -> bytes:
    image = Image.new("RGB", size, color)
    if gradient:
        for x in range(size[0]):
            for y in range(size[1]):
                image.putpixel((x, y), (color[0], (x * 4) % 256, (y * 5) % 256))
    out = io.BytesIO()
    image.save(out, format="JPEG")
    return out.getvalue()


def _photo(client, headers, room_id=None):
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _confirm(att, status="photo"):
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck).where(ChatPhotoCheck.attachment_id == att).values(status=status)
        )
        db.commit()


def _ready(client, owner, uploader):
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=owner).status_code == 200
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=uploader).status_code == 200
    )


def _eligible(client, a):
    _ready(client, a, a)
    att, msg = _photo(client, a)
    _confirm(att)
    return att, msg


def _enqueue(att):
    with SessionLocal() as db:
        return js.enqueue(db, att, KIND)


def _job(att):
    with SessionLocal() as db:
        return jobs.get_by_attachment(db, att, KIND)


def _embedding(att):
    with SessionLocal() as db:
        return db.get(PhotoEmbedding, att)


def _emb_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PhotoEmbedding))


# ---------- 인코더: 차원·정규화·재현성·검증 ----------
def test_fake_encoder_gives_a_normalized_vector_of_the_right_dimension_reproducibly():
    enc = encoder.FakeEncoder()
    enc.load()
    first, second = enc.encode(_jpeg()), enc.encode(_jpeg())
    assert len(first) == enc.dim == 16 and first == second  # 같은 입력 → 같은 결과
    assert abs(sum(v * v for v in first) - 1.0) < 1e-9
    assert encoder.validate(first, enc.dim) == first
    assert enc.encode(_jpeg(color=(10, 200, 10))) != first  # 다른 입력 → 다른 결과


def test_a_flat_color_image_still_gets_a_valid_distinct_vector():
    enc = encoder.FakeEncoder()
    flat_a = enc.encode(_jpeg((128, 128, 128), gradient=False))
    flat_b = enc.encode(_jpeg((120, 130, 128), gradient=False))
    for v in (flat_a, flat_b):
        encoder.validate(v, enc.dim)


def test_pack_unpack_round_trips_float32():
    vec = encoder.FakeEncoder().encode(_jpeg())
    blob = encoder.pack(vec)
    assert len(blob) == 16 * 4
    back = encoder.unpack(blob, 16)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vec, back, strict=True))
    with pytest.raises(encoder.EncoderError):
        encoder.unpack(blob, 15)


@pytest.mark.parametrize(
    ("vector", "dim", "code"),
    [
        ([0.1, 0.2], 3, "DimensionMismatch"),
        ([float("nan"), 1.0], 2, "InvalidVector"),
        ([float("inf"), 1.0], 2, "InvalidVector"),
        ([0.5, 0.5], 2, "NotNormalized"),
        ([3.0, 4.0], 2, "NotNormalized"),
    ],
)
def test_validate_rejects_bad_vectors(vector, dim, code):
    with pytest.raises(encoder.EncoderError, match=code):
        encoder.validate(vector, dim)


@pytest.mark.parametrize("vector", [[], [0.0, 0.0], [float("nan")], [float("inf"), 1.0]])
def test_normalize_rejects_empty_zero_and_non_finite_vectors(vector):
    with pytest.raises(encoder.EncoderError, match="InvalidVector"):
        encoder.normalize(vector)


def test_preprocess_rejects_broken_oversize_and_non_image_input_without_leaking_content():
    with pytest.raises(encoder.EncoderError, match="InvalidImage") as err:
        encoder.preprocess(b"not an image: secret family note")
    assert "secret" not in str(err.value)
    huge = io.BytesIO()
    Image.new("L", (6000, 5000)).save(huge, format="PNG")  # 3천만 화소 > 상한
    with pytest.raises(encoder.EncoderError, match="ImageTooLarge"):
        encoder.preprocess(huge.getvalue())


def test_preprocess_drops_metadata_and_applies_exif_rotation():
    image = Image.new("RGB", (40, 20), (1, 2, 3))
    exif = Image.Exif()
    exif[0x0112] = 6  # 90도 회전
    exif[0x010F] = "Camera Maker"
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    processed = encoder.preprocess(out.getvalue())
    assert processed.size == (20, 40) and processed.info == {}


# ---------- 모델 초기화 실패·OOM ----------
def test_siglip2_without_a_model_path_or_files_fails_to_load_without_downloading(monkeypatch):
    with pytest.raises(encoder.EncoderUnavailable, match="ModelPathMissing"):
        encoder.Siglip2Encoder("").load()
    import os

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    with pytest.raises(
        encoder.EncoderUnavailable
    ):  # 없는 폴더·torch 없는 환경: 어느 쪽이든 오류로 끝난다
        encoder.Siglip2Encoder(r"C:\no\such\siglip2\snapshot").load()
    assert os.environ.get("HF_HUB_OFFLINE") == "1"  # 오프라인 강제: 다운로드 경로를 막는다


class _OutOfMemoryError(RuntimeError):
    pass


_OutOfMemoryError.__name__ = "OutOfMemoryError"


def _fake_siglip(error: Exception | None):
    """torch·모델 없이 `Siglip2Encoder.encode` 의 오류 처리만 보는 껍데기."""
    emptied = []
    enc = encoder.Siglip2Encoder("x")
    enc._device = "cuda"
    enc._torch = SimpleNamespace(
        inference_mode=lambda: __import__("contextlib").nullcontext(),
        is_tensor=lambda o: True,
        cuda=SimpleNamespace(
            empty_cache=lambda: emptied.append(1),
            memory_allocated=lambda: 0,
            memory_reserved=lambda: 0,
        ),
    )

    def features(pixel_values):
        if error:
            raise error
        raise AssertionError("이 시험은 항상 오류를 낸다")

    enc._model = SimpleNamespace(
        get_image_features=features, parameters=lambda: iter([SimpleNamespace(dtype=None)])
    )
    enc._processor = lambda images, return_tensors: {
        "pixel_values": SimpleNamespace(to=lambda *a, **k: None)
    }
    return enc, emptied


def test_gpu_out_of_memory_is_reported_as_a_resource_error_and_the_cache_is_cleared():
    enc, emptied = _fake_siglip(_OutOfMemoryError("CUDA out of memory. Tried to allocate 2 GiB"))
    with pytest.raises(encoder.EncoderResourceError, match="OutOfMemory"):
        enc.encode(_jpeg())
    assert emptied == [1]  # 자원 정리


def test_other_inference_failures_become_encoder_errors_with_only_the_kind_name():
    enc, emptied = _fake_siglip(ValueError("라벨: 비밀 사진 설명"))
    with pytest.raises(encoder.EncoderError) as err:
        enc.encode(_jpeg())
    assert "비밀" not in str(err.value) and "InferValueError" in str(err.value) and emptied == []


# ---------- 워커 연동(가짜 인코더) ----------
def test_worker_makes_and_saves_an_embedding_for_an_eligible_photo(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    assert _enqueue(att).outcome == "queued"
    analysis.register_handlers()
    assert worker.run_once("w1") == "done"
    row = _embedding(att)
    assert (row.model_id, row.model_version, row.dim) == ("fake-gray4x4", "1", 16)
    vec = encoder.unpack(row.vector, row.dim)
    encoder.validate(vec, row.dim)
    assert _job(att).status == "done"
    assert worker.run_once("w1") is None


def test_the_same_photo_gives_the_same_embedding_after_a_rerun(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    analysis.register_handlers()
    worker.run_once("w1")
    first = _embedding(att).vector
    with SessionLocal() as db:  # 결과를 지우고 같은 사진을 다시 돌린다
        emb.delete_for_attachment(db, att)
        jobs.delete_done_for_attachment(db, KIND, att)
        db.commit()
    assert _enqueue(att).outcome == "queued"
    worker.run_once("w1")
    assert _embedding(att).vector == first


def test_web_process_does_not_register_the_embedding_handler_or_load_a_model():
    assert KIND not in worker._handlers and analysis._encoder is None
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(encoder))
    top_level_imports = {
        (n.module if isinstance(n, ast.ImportFrom) else a.name).split(".")[0]
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not top_level_imports & {
        "torch",
        "transformers",
    }  # 무거운 라이브러리는 load() 안에서만 가져온다


def test_encoder_off_means_nothing_runs_and_a_failed_load_counts_as_a_retry(
    client, family, monkeypatch
):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    monkeypatch.setattr(settings, "family_memory_encoder", "off")
    analysis.register_handlers()
    assert worker.run_once("w1") == "retry"
    row = _job(att)
    assert (row.status, row.attempts, row.last_error) == ("queued", 1, "EncoderUnavailable")
    assert _emb_count() == 0


def test_gpu_oom_fails_the_job_with_backoff_and_stops_at_the_limit_without_a_result(
    client, family, monkeypatch
):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    boom = encoder.FakeEncoder(fail_with=encoder.EncoderResourceError("OutOfMemory"))
    monkeypatch.setattr(analysis, "_encoder", boom)
    analysis.register_handlers()
    now = datetime.now(UTC)
    outcomes = []
    for n in range(js.MAX_ATTEMPTS):
        with SessionLocal() as db:
            job = js.claim(db, "w1", [KIND], now)
        assert job is not None and job.attempts == n + 1
        try:
            analysis.run(job)
        except encoder.EncoderResourceError as exc:
            with SessionLocal() as db:
                outcomes.append(js.fail(db, job, "w1", type(exc).__name__, now))
        now += jobs.BACKOFF_CAP
    assert outcomes == ["retry", "retry", "failed"]
    row = _job(att)
    assert (row.status, row.last_error) == ("failed", "EncoderResourceError")
    assert _emb_count() == 0


def test_a_missing_photo_file_fails_the_job_instead_of_crashing_the_worker(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    analysis.photo_file(att).unlink()
    analysis.register_handlers()
    assert worker.run_once("w1") == "retry"
    assert _job(att).last_error == "EncoderError" and _emb_count() == 0


# ---------- 자격 재확인·저장 차단·경합 ----------
def test_one_to_one_and_unconfirmed_photos_cannot_be_enqueued_for_embedding(client, family):
    a, b, _ = family
    _ready(client, a, a)
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    direct, _ = _photo(client, a, room_id=room["id"])
    _confirm(direct)
    assert _enqueue(direct).outcome == "rejected"
    for status in ("pending", "unsure", "failed", "document"):
        att, _ = _photo(client, a)
        _confirm(att, status)
        assert _enqueue(att).reason == "not_confirmed_photo"
    assert (
        _job(direct) is None and _emb_count() == 0
    )  # D-13: 확인되지 않은 사진은 자동 승격 없이 거절


def test_withdrawal_while_the_encoder_runs_blocks_the_result(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)

    def run_then_withdraw(job):
        result = analysis.run(job)
        assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
        return result

    worker.register_handler(KIND, run_then_withdraw, analysis.save)
    assert worker.run_once("w1") == "lost"  # 철회가 작업을 막았으므로 저장되지 않는다
    assert _emb_count() == 0 and _job(att).status == "canceled"


@pytest.mark.parametrize("cause", ["exclude", "family_off", "delete"])
def test_exclusion_family_off_and_deletion_while_running_block_the_result(client, family, cause):
    a, _, _ = family
    att, msg = _eligible(client, a)
    _enqueue(att)

    def run_then(job):
        result = analysis.run(job)
        if cause == "exclude":
            r = client.put(f"{BASE}/photos/{att}/exclusion", json={"excluded": True}, headers=a)
        elif cause == "family_off":
            r = client.put(f"{BASE}/settings", json={"enabled": False}, headers=a)
        else:
            r = client.delete(f"{MSG}/{msg}", headers=a)
        assert r.status_code == 200
        return result

    worker.register_handler(KIND, run_then, analysis.save)
    assert worker.run_once("w1") == "lost" and _emb_count() == 0


def test_a_worker_that_lost_its_lease_cannot_store_its_late_result(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    t0 = datetime.now(UTC)
    with SessionLocal() as db:
        slow = js.claim(db, "slow", [KIND], t0)
    result = analysis.run(slow)  # 느린 워커가 결과를 만들었지만 아직 저장하지 못했다
    late = t0 + timedelta(seconds=settings.family_memory_job_lease_seconds + 1)
    with SessionLocal() as db:
        js.claim(db, "fast", [KIND], late)  # 임대 만료 복구(backoff 중이라 아직 못 가져간다)
    with SessionLocal() as db:
        fast = js.claim(db, "fast", [KIND], late + timedelta(seconds=31))
    assert fast is not None and fast.attempts == 2
    with SessionLocal() as db:
        assert js.complete(db, slow, "slow", result, analysis.save) == "lost"
    assert _emb_count() == 0
    with SessionLocal() as db:
        assert js.complete(db, fast, "fast", analysis.run(fast), analysis.save) == "done"
    assert _emb_count() == 1


def test_duplicate_enqueue_creates_one_job_and_one_embedding(client, family):
    a, _, _ = family
    att, _ = _eligible(client, a)
    assert [_enqueue(att).outcome for _ in range(3)] == ["queued", "exists", "exists"]
    analysis.register_handlers()
    assert worker.run_once("w1") == "done" and worker.run_once("w1") is None
    assert _emb_count() == 1
    assert _enqueue(att).outcome == "exists"  # 끝난 사진을 다시 등록해도 다시 만들지 않는다


# ---------- 파생 결과 정리 ----------
def _embed_one(client, a):
    att, msg = _eligible(client, a)
    _enqueue(att)
    analysis.register_handlers()
    assert worker.run_once("w1") == "done" and _embedding(att) is not None
    return att, msg


def test_withdrawal_deletes_the_embedding_and_a_re_consent_allows_a_fresh_analysis(client, family):
    a, _, _ = family
    att, _ = _embed_one(client, a)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert _embedding(att) is None and _job(att) is None  # 파생 결과와 끝난 작업 줄이 모두 사라진다
    assert _enqueue(att).reason == "no_consent"
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    assert _enqueue(att).outcome == "queued"  # 재동의 뒤에는 새로 분석할 수 있다
    assert worker.run_once("w1") == "done" and _embedding(att) is not None


def test_exclusion_family_off_and_deletion_delete_the_embedding(client, family):
    a, _, _ = family
    excluded, _ = _embed_one(client, a)
    assert (
        client.put(
            f"{BASE}/photos/{excluded}/exclusion", json={"excluded": True}, headers=a
        ).status_code
        == 200
    )
    assert _embedding(excluded) is None and _job(excluded) is None
    kept, _ = _photo(client, a)
    _confirm(kept)
    _enqueue(kept)
    worker.run_once("w1")
    assert _embedding(kept) is not None
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    assert _emb_count() == 0 and _job(kept) is None
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    third, msg = _eligible_after(client, a)
    assert client.delete(f"{MSG}/{msg}", headers=a).status_code == 200
    assert _embedding(third) is None and _job(third) is None


def _eligible_after(client, a):
    """가족 활성화·동의가 이미 있는 상태에서 새 사진 하나를 임베딩까지 만든다."""
    client.put(f"{BASE}/consent", json={"consent": True}, headers=a)
    att, msg = _photo(client, a)
    _confirm(att)
    _enqueue(att)
    worker.run_once("w1")
    assert _embedding(att) is not None
    return att, msg


def test_leaving_the_family_deletes_only_that_members_embeddings(client, family):
    a, b, _ = family
    _ready(client, a, a)
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=b).status_code == 200
    mine, _ = _photo(client, a)
    theirs, _ = _photo(client, b)
    for att in (mine, theirs):
        _confirm(att)
        _enqueue(att)
    analysis.register_handlers()
    assert worker.run_once("w1") == "done" and worker.run_once("w1") == "done"
    assert _emb_count() == 2
    assert client.post(LEAVE, headers=b).status_code == 204
    assert _embedding(theirs) is None and _embedding(mine) is not None


def test_families_are_isolated_and_a_cleanup_failure_rolls_back_the_withdrawal(
    client, family, other_family, monkeypatch
):
    a, _, _ = family
    att, _ = _embed_one(client, a)
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
    worker.run_once("w1")
    assert _emb_count() == 2
    assert (
        client.put(f"{BASE}/consent", json={"consent": False}, headers=other_family).status_code
        == 200
    )
    assert _embedding(other_att) is None and _embedding(att) is not None  # 다른 가족은 그대로

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(emb, "delete_for_user", boom)
    with pytest.raises(RuntimeError):
        client.put(f"{BASE}/consent", json={"consent": False}, headers=a)
    assert client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is True
    assert _embedding(att) is not None  # 반쪽 상태 없음


def test_cleanup_hooks_run_after_the_job_blocking_hooks():
    """진행 중이던 저장이 있으면 작업 줄 잠금 때문에 그 저장이 끝난 뒤에 지워지도록, 작업 차단 훅이 먼저 불려야 한다."""
    for hooks, job_fn, emb_fn in (
        (memory_hooks._member_withdrawn, js._on_member_withdrawn, analysis._on_member_withdrawn),
        (memory_hooks._family_disabled, js._on_family_disabled, analysis._on_family_disabled),
        (memory_hooks._photo_excluded, js._on_photo_excluded, analysis._on_photo_excluded),
        (
            memory_hooks._attachment_removed,
            js._on_attachment_removed,
            analysis._on_attachment_removed,
        ),
    ):
        assert hooks.index(job_fn) < hooks.index(emb_fn)


# ---------- 로그·개인정보 ----------
def test_logs_and_records_hold_no_photo_content_or_paths(client, family, caplog):
    a, _, _ = family
    att, _ = _eligible(client, a)
    _enqueue(att)
    analysis.register_handlers()
    with caplog.at_level(logging.INFO):
        assert worker.run_once("w1") == "done"
    row = _job(att)
    text = caplog.text + str(row.last_error) + str(row.cancel_reason)
    assert "chat_photos" not in text and att not in text and ".jpg" not in text


def test_the_embedding_row_has_no_photo_content_columns():
    assert set(PhotoEmbedding.__table__.columns.keys()) == {
        "attachment_id",
        "group_id",
        "user_id",
        "model_id",
        "model_version",
        "dim",
        "vector",
        "created_at",
    }
    assert FamilyMemoryJob.__table__.c.last_error.type.length == 40


# ---------- 별도 워커 프로세스 진입점 ----------
def test_worker_main_refuses_to_start_unless_everything_is_enabled(monkeypatch):
    assert settings.family_memory_worker_enabled is False
    assert worker_main.main() == worker_main.EXIT_NOT_ENABLED
    monkeypatch.setattr(settings, "family_memory_worker_enabled", True)
    monkeypatch.setattr(settings, "family_memory_encoder", "off")
    assert worker_main.main() == worker_main.EXIT_NOT_ENABLED
    assert KIND not in worker._handlers


def test_worker_main_exits_with_a_code_when_the_model_cannot_be_loaded(monkeypatch):
    monkeypatch.setattr(settings, "family_memory_worker_enabled", True)
    monkeypatch.setattr(settings, "family_memory_encoder", "siglip2")
    monkeypatch.setattr(settings, "family_memory_siglip2_path", "")
    assert (
        worker_main.main() == worker_main.EXIT_ENCODER_FAILED
    )  # 모델 경로 없음: 작업은 건드리지 않는다
    assert KIND not in worker._handlers


def test_worker_main_registers_the_handler_and_cleans_up_on_exit(monkeypatch):
    monkeypatch.setattr(settings, "family_memory_worker_enabled", True)
    loops = []
    monkeypatch.setattr(worker, "_loop", lambda: loops.append(1))
    assert worker_main.main() == 0
    assert loops == [1] and KIND in worker._handlers and analysis._encoder is None
