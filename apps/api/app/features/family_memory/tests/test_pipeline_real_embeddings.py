"""실제 SigLIP2 임베딩으로 본 전체 흐름(PR9). 합성 장면 이미지의 **실제 모델 임베딩**(승인된 로컬 모델, `scripts/siglip2_scene_fixture.py` 가 torch 가 있는 환경에서 만든 고정 자료)을
재생하는 인코더로 워커 → 임베딩 저장 → 그룹화 → 후보 → API 를 끝까지 본다. 이 시험은 torch·모델 파일이 필요 없다(고정 자료만 읽는다). 실제 가족 사진은 쓰지 않는다.

한계: 모델 추론 자체는 이 환경(Python 3.14, torch 없음)에서 돌지 않고 고정 자료를 재생한다. 추론은 `scripts/siglip2_smoke.py`·`siglip2_scene_fixture.py` 가 별도 환경에서 확인한다."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_memory import analysis, candidate_service, worker
from app.features.family_memory import job_service as js
from app.features.family_memory.models import MemoryCandidate, PhotoEmbedding
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests import synthetic_scenes as scenes

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
KIND = analysis.KIND_EMBEDDING
FIXTURE = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "siglip2_synthetic_scenes.json"
)
CONFIRM = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}
DAY = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)


class ReplayEncoder:
    """고정 자료의 실제 SigLIP2 임베딩을 돌려주는 인코더: 저장된 사진의 작은 지문이 가장 가까운 합성 장면을 찾아 그 임베딩을 준다(재압축돼도 같은 장면으로 찾는다)."""

    def __init__(self) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.model_id, self.model_version, self.dim = (
            data["model_id"],
            data["model_version"][:40],
            data["dim"],
        )
        self.photos = data["photos"]

    def load(self) -> None:
        pass

    def resources(self) -> dict:
        return {"rss_mb": None, "gpu_alloc_mb": None, "gpu_reserved_mb": None}

    def encode(self, data: bytes) -> list[float]:
        sig = scenes.signature(data)
        best = min(
            self.photos,
            key=lambda p: sum(abs(a - b) for a, b in zip(p["signature"], sig, strict=True)),
        )
        return list(best["embedding"])


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    saved = dict(worker._handlers)
    analysis.reset_encoder()
    monkeypatch.setattr(analysis, "_encoder", ReplayEncoder())
    yield
    analysis._encoder = None
    worker._handlers.clear()
    worker._handlers.update(saved)


def _gid(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


_n = [0]


def _upload(client, headers, scene: str, variant: int, when: datetime):
    from app.features.family_chat import photo_check_service as pcs
    from app.features.family_chat import photo_service as ps

    ps.upload_limiter._failures.clear()
    pcs.check_limiter._failures.clear()  # 시험이 사진을 많이 올리고 확인한다
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", scenes.jpeg_bytes(scene, variant), "image/jpeg")},
        data={"taken_at": when.isoformat()},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    with SessionLocal() as db:
        assert checks.record_auto(db, _gid(client, headers), att, "unsure")
    assert client.post(f"{PHOTOS}/{att}/check", json=CONFIRM, headers=headers).status_code == 200
    return att


def _event(client, headers, start: datetime) -> list[str]:
    """한 사건: 세 장면 × 변형 4장을 30분 안에 올린다(같은 장면의 변형끼리는 거의 같은 사진, 장면끼리는 서로 다른 사진)."""
    out = []
    for i, scene in enumerate(scenes.SCENES):
        for v in range(scenes.VARIANTS):
            out.append(
                _upload(
                    client,
                    headers,
                    scene,
                    v,
                    start + timedelta(minutes=2 * (i * scenes.VARIANTS + v)),
                )
            )
    return out


def _run_all(atts: list[str]) -> None:
    for att in atts:
        assert js.enqueue(SessionLocal(), att, KIND).outcome == "queued"
    analysis.register_handlers()
    for _ in atts:
        assert worker.run_once("w1") == "done"


def _ready(client, headers):
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=headers).status_code == 200
    )
    assert (
        client.put(
            f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=headers
        ).status_code
        == 200
    )


def test_real_siglip2_embeddings_flow_through_the_worker_grouping_and_api(client, family):
    a, _, _ = family
    _ready(client, a)
    atts = _event(client, a, DAY)
    _run_all(atts)
    with SessionLocal() as db:
        rows = db.scalars(select(PhotoEmbedding)).all()
    assert len(rows) == 12 and {r.dim for r in rows} == {
        768
    }  # 실제 모델의 768차원 벡터가 사진마다 저장된다
    assert {r.model_id for r in rows} == {"siglip2-base-patch16-224"}
    with SessionLocal() as db:
        result = candidate_service.refresh(db, _gid(client, a))
    assert (result.created, result.eligible) == (1, 12)
    [item] = client.get(f"{BASE}/candidates", headers=a).json()["items"]
    assert item["photo_count"] == 12 and item["status"] == "private"
    # 같은 장면의 변형(코사인 0.97 이상)은 중복 후보로 묶이고 서로 다른 장면은 따로 남는다: 대표는 장면마다 다르다
    with SessionLocal() as db:
        from app.features.family_memory.models import MemoryCandidatePhoto

        dup_rows = db.scalars(
            select(MemoryCandidatePhoto).where(MemoryCandidatePhoto.duplicate_of.is_not(None))
        ).all()
        reps = db.scalars(
            select(MemoryCandidatePhoto).where(MemoryCandidatePhoto.rank.is_not(None))
        ).all()
    assert len(dup_rows) >= 3 and len(reps) == 3


def test_the_same_scenes_days_apart_are_never_merged_but_overnight_with_identical_scenes_is_bridged(
    client, family
):
    """같은 장면(실제 임베딩이 거의 같다)이라도 사흘 간격이면 따로이고(다른 연도는 더욱), 36시간 안(여기서는 10시간 뒤)이면 하룻밤 이어진 한 이벤트 후보(`bridged`)로 묶인다 — 설계된 동작."""
    a, _, _ = family
    _ready(client, a)
    first = _event(client, a, DAY)
    far = _event(client, a, DAY + timedelta(hours=72))
    _run_all(first + far)
    with SessionLocal() as db:
        assert candidate_service.refresh(db, _gid(client, a)).created == 2
    items = client.get(f"{BASE}/candidates", headers=a).json()["items"]
    assert (
        len(items) == 2
        and {i["photo_count"] for i in items} == {12}
        and not any(i["bridged"] for i in items)
    )
    assert {p["attachment_id"] for p in items[0]["photos"]}.isdisjoint(
        {p["attachment_id"] for p in items[1]["photos"]}
    )
    night = _event(
        client, a, DAY + timedelta(hours=82)
    )  # 첫 사건의 10시간 뒤에 같은 장면이 또 올라온다
    _run_all(night)
    with SessionLocal() as db:
        candidate_service.refresh(db, _gid(client, a))
    merged = [
        i for i in client.get(f"{BASE}/candidates", headers=a).json()["items"] if i["bridged"]
    ]
    assert len(merged) == 1 and merged[0]["photo_count"] == 24


def test_worker_restart_and_lease_expiry_do_not_duplicate_embeddings_or_candidates(client, family):
    a, _, _ = family
    _ready(client, a)
    atts = _event(client, a, DAY)
    for att in atts:
        with SessionLocal() as db:
            js.enqueue(db, att, KIND)
    analysis.register_handlers()
    t0 = datetime.now(UTC)
    with SessionLocal() as db:
        crashed = js.claim(db, "crashed", [KIND], t0)  # 워커가 작업을 잡은 채 죽었다(서버 재시작)
    assert crashed is not None
    later = t0 + timedelta(seconds=settings.family_memory_job_lease_seconds + 60)
    done = 0
    while True:  # 새 워커가 임대 만료·backoff 뒤 이어서 모두 처리한다
        with SessionLocal() as db:
            job = js.claim(db, "fresh", [KIND], later)
        if job is None:
            later += timedelta(minutes=2)
            with SessionLocal() as db:
                job = js.claim(db, "fresh", [KIND], later)
            if job is None:
                break
        result = analysis.run(job)
        with SessionLocal() as db:
            assert js.complete(db, job, "fresh", result, analysis.save) == "done"
        done += 1
    assert done == 12
    with SessionLocal() as db:
        assert (
            js.complete(db, crashed, "crashed", analysis.run(crashed), analysis.save) == "lost"
        )  # 죽었다 살아난 워커의 늦은 결과는 버려진다
        assert (
            db.scalar(select(func.count()).select_from(PhotoEmbedding)) == 12
        )  # 사진마다 한 벌(중복 없음)
        candidate_service.refresh(db, _gid(client, a))
        candidate_service.refresh(db, _gid(client, a))
        assert (
            db.scalar(select(func.count()).select_from(MemoryCandidate)) == 1
        )  # 새로 고침을 반복해도 후보는 한 벌
