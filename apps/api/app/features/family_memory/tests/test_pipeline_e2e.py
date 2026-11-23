"""AI 추억 전체 흐름 통합 시험(PR8): 사진 확인 → 업로더 동의 → 분석 작업 등록 → 워커 → 임베딩(가짜 인코더) → 그룹화 → 후보 새로 고침 → 후보 조회 API.
그리고 같은 흐름 위에서 개인정보 시나리오(철회·사진별 제외·사진 삭제·가족 나가기·가족 기능 끄기·실행 중 철회·정리 실패)가 **작업·임베딩·후보·API 를 모두 막는지** 본다.
합성 이미지·합성 값만 쓰고, 자동 enqueue·refresh 진입점이 없으므로 격리된 시험 환경에서 명시적으로 호출한다(운영 코드는 활성화하지 않는다)."""

import io
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_memory import (
    analysis,
    candidate_repository,
    candidate_service,
    reconcile,
    worker,
)
from app.features.family_memory import embedding_repository as emb
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
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
LEAVE = "/family-group/groups/me/leave"
KIND = analysis.KIND_EMBEDDING
DAY = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
CONFIRM = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}
FIXTURE = (
    Path(__file__).resolve().parents[6]
    / "docs"
    / "contracts"
    / "fixtures"
    / "family_memory_candidates.json"
)
_counter = [0]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    monkeypatch.setattr(settings, "family_memory_encoder", "fake")
    saved_handlers = dict(worker._handlers)
    saved_hooks = (
        list(memory_hooks._member_withdrawn),
        list(memory_hooks._family_disabled),
        list(memory_hooks._photo_excluded),
        list(memory_hooks._attachment_removed),
    )
    analysis.reset_encoder()
    yield
    analysis.reset_encoder()
    worker._handlers.clear()
    worker._handlers.update(saved_handlers)
    memory_hooks._member_withdrawn[:] = saved_hooks[0]
    memory_hooks._family_disabled[:] = saved_hooks[1]
    memory_hooks._photo_excluded[:] = saved_hooks[2]
    memory_hooks._attachment_removed[:] = saved_hooks[3]


def _image(seed: int) -> bytes:
    rng = random.Random(seed)
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


def _upload(client, headers, minutes: int):
    from app.features.family_chat import photo_service as ps

    ps.upload_limiter._failures.clear()
    _counter[0] += 1
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _image(_counter[0]), "image/jpeg")},
        data={"taken_at": (DAY + timedelta(minutes=minutes)).isoformat()},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"], r.json()["id"]


def _confirm_as_uploader(client, headers, att):
    """실제 경로로 일반 사진 확인: 자동 판별이 애매(unsure)로 끝난 사진을 업로더가 직접 일반 사진으로 확인한다(D-13)."""
    with SessionLocal() as db:
        from app.features.family_chat import photo_check_repository as checks

        assert checks.record_auto(db, _gid(client, headers), att, "unsure")
    r = client.post(f"{PHOTOS}/{att}/check", json=CONFIRM, headers=headers)
    assert r.status_code == 200, r.text


def _enqueue(att):
    with SessionLocal() as db:
        return js.enqueue(db, att, KIND)


def _count(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _embedding_ids():
    with SessionLocal() as db:
        return set(db.scalars(select(PhotoEmbedding.attachment_id)))


def _candidate_photo_ids():
    with SessionLocal() as db:
        return set(db.scalars(select(MemoryCandidatePhoto.attachment_id)))


def _job_atts():
    with SessionLocal() as db:
        return set(db.scalars(select(FamilyMemoryJob.attachment_id)))


def _api(client, headers):
    r = client.get(f"{BASE}/candidates", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _api_ids(client, headers):
    return {p["attachment_id"] for item in _api(client, headers) for p in item["photos"]}


def _family_ready(client, owner, *uploaders):
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=owner).status_code == 200
    for u in uploaders:
        r = client.put(f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=u)
        assert r.status_code == 200, r.text


def _run_pipeline(client, headers, n=4, start=0):
    """업로드 → 확인 → 작업 등록 → 워커 처리 → 후보 새로 고침까지 한 번에. 단계마다 결과를 검사하고 (사진 id 목록)을 돌려준다."""
    made = [_upload(client, headers, start + i * 5) for i in range(n)]
    for att, _ in made:
        _confirm_as_uploader(client, headers, att)
        assert _enqueue(att).outcome == "queued"
    analysis.register_handlers()
    for _ in made:
        assert worker.run_once("w1") == "done"
    return made


def _refresh(client, headers):
    with SessionLocal() as db:
        return candidate_service.refresh(db, _gid(client, headers))


# ---------- 전체 흐름 ----------
def test_full_pipeline_from_confirmed_photos_to_the_candidate_api(client, family):
    a, _, group = family
    _family_ready(client, a, a)
    made = _run_pipeline(client, a)
    atts = {m[0] for m in made}
    assert (
        _embedding_ids() == atts and _count(FamilyMemoryJob) == 4
    )  # 임베딩(가짜 인코더)이 사진마다 한 벌
    result = _refresh(client, a)
    assert (result.created, result.eligible) == (1, 4)
    items = _api(client, a)
    assert len(items) == 1 and {p["attachment_id"] for p in items[0]["photos"]} == atts
    assert items[0]["status"] == "private" and items[0]["dated_count"] == 4
    # 자동 게시 없음: 서랍·채팅에 아무것도 보내지 않았고 후보는 비공개 상태로만 있다
    with SessionLocal() as db:
        assert set(db.scalars(select(MemoryCandidate.status))) == {"private"}


def test_each_stage_is_blocked_with_a_reason_when_a_precondition_is_missing(client, family):
    a, b, _ = family
    att, _ = _upload(client, a, 0)
    assert _enqueue(att).reason == "family_off"  # ① 가족 설정 꺼짐
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    assert _enqueue(att).reason == "no_consent"  # ② 업로더 동의 없음
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    assert (
        _enqueue(att).reason == "not_confirmed_photo"
    )  # ③ 일반 사진 확인 전(D-13: 자동 승격 없음)
    _confirm_as_uploader(client, a, att)
    analysis.register_handlers()
    monkey_off = settings.family_memory_encoder
    settings.family_memory_encoder = "off"
    try:
        assert _enqueue(att).outcome == "queued"
        assert worker.run_once("w1") == "retry"  # ④ 인코더 꺼짐: 작업이 재시도로 남고 임베딩은 없다
        assert _embedding_ids() == set()
    finally:
        settings.family_memory_encoder = monkey_off
    # ⑤ 후보: 임베딩 단계가 끝나지 않아도 시간 근거로 후보가 만들어질 수 있지만 사진이 3장 미만이면 후보가 없다
    assert _refresh(client, a).created == 0 and _api(client, a) == [] and b


# ---------- 개인정보 시나리오 ----------
def _setup_two_uploaders(client, a, b):
    _family_ready(client, a, a, b)
    mine = _run_pipeline(client, a, n=4, start=0)
    theirs = _run_pipeline(client, b, n=4, start=300)  # 5시간 뒤 다른 사람의 사진
    _refresh(client, a)
    return mine, theirs


EVENTS = ["withdraw", "exclude", "delete", "leave", "family_off"]


def _apply(event, client, a, b, mine, theirs):
    """b(두 번째 업로더)에게 이벤트를 적용하고, 영향받는 사진 id 집합을 돌려준다."""
    if event == "withdraw":
        assert client.put(f"{BASE}/consent", json={"consent": False}, headers=b).status_code == 200
        return {t[0] for t in theirs}
    if event == "exclude":
        att = theirs[0][0]
        assert (
            client.put(
                f"{BASE}/photos/{att}/exclusion", json={"excluded": True}, headers=b
            ).status_code
            == 200
        )
        return {att}
    if event == "delete":
        att, msg = theirs[0]
        assert client.delete(f"{MSG}/{msg}", headers=b).status_code == 200
        return {att}
    if event == "leave":
        assert client.post(LEAVE, headers=b).status_code in (200, 204)
        return {t[0] for t in theirs}
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    return {m[0] for m in mine} | {t[0] for t in theirs}  # 가족 전체


@pytest.mark.parametrize("event", EVENTS)
def test_privacy_events_block_jobs_embeddings_candidates_and_the_api(
    client, family, other_family, event
):
    a, b, _ = family
    mine, theirs = _setup_two_uploaders(client, a, b)
    # 다른 가족도 같은 흐름을 끝낸 상태(격리 확인용)
    other_id = _uid(client, other_family)
    assert other_id
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=other_family).status_code
        == 200
    )
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=other_family).status_code
        == 200
    )
    other = _run_pipeline(client, other_family, n=4, start=0)
    _refresh(client, other_family)
    assert len(_api(client, a)) == 2 and len(_api(client, other_family)) == 1
    affected = _apply(event, client, a, b, mine, theirs)

    # ① 임베딩·작업·후보 줄이 지워졌다
    assert _embedding_ids().isdisjoint(affected)
    assert _job_atts().isdisjoint(affected)
    assert _candidate_photo_ids().isdisjoint(affected)
    # ② API 에 영향받는 사진이 나오지 않는다(재검증 + 정리)
    assert _api_ids(client, a).isdisjoint(affected)
    # ③ 영향받는 사진은 다시 작업으로 등록되지 않는다(삭제된 사진 포함)
    for att in affected:
        assert _enqueue(att).outcome == "rejected"
    # ④ 영향받지 않는 사진·다른 가족은 그대로다
    untouched = ({m[0] for m in mine} | {t[0] for t in theirs}) - affected
    if event != "family_off":
        assert untouched <= _embedding_ids()
        assert _api_ids(client, a) <= untouched
    assert {o[0] for o in other} <= _embedding_ids()
    assert _api_ids(client, other_family) == {o[0] for o in other}
    # ⑤ 영향받는 쪽 사용자가 다른 가족의 후보를 볼 수 없다
    assert _api_ids(client, other_family).isdisjoint({m[0] for m in mine} | {t[0] for t in theirs})


@pytest.mark.parametrize("event", EVENTS)
def test_an_event_during_a_running_job_discards_its_result(client, family, event):
    a, b, _ = family
    _family_ready(client, a, a, b)
    theirs = [_upload(client, b, 300 + i * 5) for i in range(4)]
    for att, _ in theirs:
        _confirm_as_uploader(client, b, att)
    mine = [_upload(client, a, i * 5) for i in range(4)]
    for att, _ in mine:
        _confirm_as_uploader(client, a, att)
    target = theirs[0][0]
    assert _enqueue(target).outcome == "queued"

    def run_then_event(job):
        result = analysis.run(job)  # 분석은 끝났지만 아직 저장 전
        _apply(event, client, a, b, [(m[0], m[1]) for m in mine], theirs)
        return result

    worker.register_handler(KIND, run_then_event, analysis.save)
    outcome = worker.run_once("w1")
    # 제외·철회·삭제·나가기·가족 끄기 어느 경우든 저장되지 않는다
    assert outcome in ("lost", "canceled")
    assert target not in _embedding_ids()


def test_withdrawal_is_kept_when_every_cleanup_step_fails_and_failures_are_logged_without_ids(
    client, family, monkeypatch, caplog
):
    a, b, _ = family
    mine, theirs = _setup_two_uploaders(client, a, b)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(candidate_repository, "candidate_ids_with_photos", boom)
    monkeypatch.setattr(emb, "delete_for_user", boom)
    monkeypatch.setattr(jobs, "cancel_for_user", boom)
    with caplog.at_level(logging.WARNING):
        assert client.put(f"{BASE}/consent", json={"consent": False}, headers=b).status_code == 200
    assert client.get(f"{BASE}/settings", headers=b).json()["me"]["consented"] is False  # 철회 유지
    assert (
        "memory cleanup deferred" in caplog.text and "RuntimeError" in caplog.text
    )  # 실패 기록(종류 이름만)
    assert not any(
        att in caplog.text for _, att in [(0, t[0]) for t in theirs]
    )  # 사진 id 가 로그에 없다
    assert not any(h for h in ["/chat_photos/", ".jpg"] if h in caplog.text)
    still = {t[0] for t in theirs}
    assert _embedding_ids() >= still  # 정리가 실패해 파생 데이터가 남았지만
    assert _api_ids(client, b).isdisjoint(still) and _api_ids(client, a).isdisjoint(
        still
    )  # 어느 구성원에게도 보이지 않는다
    monkeypatch.undo()
    with SessionLocal() as db:  # 대조 정리가 재시도로 지운다(실패했던 만큼)
        first = reconcile.reconcile(db)
        db.commit()
        assert first.embeddings == 4 and first.candidates >= 1
        assert reconcile.reconcile(db).total == 0  # 멱등
    assert _embedding_ids().isdisjoint(still) and _candidate_photo_ids().isdisjoint(still)
    assert _embedding_ids() >= {m[0] for m in mine}  # 다른 사람의 것은 그대로


def test_refresh_does_not_store_a_candidate_for_someone_who_withdrew_after_it_computed(
    client, family, monkeypatch
):
    """계산이 끝난 뒤(낡은 결과) 철회가 커밋돼도, 저장 직전 대조로 그 사람의 사진이 든 후보가 남지 않는다(경합 창 축소).
    SQLite 는 쓰기 연결이 하나뿐이라 진짜 끼어들기는 못 만들고, 철회 전에 계산한 결과를 철회 뒤에 저장하는 순서로 같은 상황을 만든다."""
    a, b, _ = family
    _family_ready(client, a, a, b)
    _run_pipeline(client, b, n=4)
    from app.features.family_memory import discovery

    with SessionLocal() as db:
        stale = discovery.discover_group(db, _gid(client, a))  # 자격 있는 상태에서 계산
    assert len(stale.candidates) == 1
    assert (
        client.put(f"{BASE}/consent", json={"consent": False}, headers=b).status_code == 200
    )  # 그 뒤 철회
    monkeypatch.setattr(
        discovery, "discover_group", lambda db, group_id, config=None, enforce_retro=False: stale
    )
    _refresh(client, a)  # 낡은 결과를 저장하려 해도
    assert _count(MemoryCandidate) == 0 and _count(MemoryCandidatePhoto) == 0
    assert _api(client, a) == []


# ---------- 앱과 서버의 계약 ----------
def test_the_api_response_matches_the_contract_fixture_the_app_tests_use(client, family):
    a, _, _ = family
    _family_ready(client, a, a)
    _run_pipeline(client, a)
    _refresh(client, a)
    body = client.get(f"{BASE}/candidates", headers=a).json()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def keys(x):
        if isinstance(x, dict):
            return {k: keys(v) for k, v in sorted(x.items())}
        if isinstance(x, list):
            return [keys(x[0])] if x else []
        return None

    assert keys(body) == keys(
        fixture
    )  # 앱 시험(familymemories.test.js)이 쓰는 고정 응답과 필드가 같다
    for photo in body["items"][0]["photos"]:
        assert photo["thumb_url"].startswith("/family-chat/photos/")
        assert photo["photo_url"].startswith("/family-chat/photos/")


def test_consent_version_is_checked_when_given_and_withdrawal_ignores_it(client, family):
    a, _, _ = family
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    bad = client.put(f"{BASE}/consent", json={"consent": True, "consent_version": 99}, headers=a)
    assert bad.status_code == 409 and bad.json()["code"] == "consent_version_mismatch"
    assert (
        client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is False
    )  # 동의가 기록되지 않았다
    ok = client.put(f"{BASE}/consent", json={"consent": True, "consent_version": 1}, headers=a)
    assert ok.status_code == 200 and ok.json()["me"]["consent_version"] == 1
    # 버전을 안 보내는 기존 호출은 그대로 된다(고지문 확정 전에는 선택)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    # 철회는 버전을 보지 않는다
    assert (
        client.put(
            f"{BASE}/consent", json={"consent": False, "consent_version": 99}, headers=a
        ).status_code
        == 200
    )
    # 사진 확인 상태는 이 흐름이 바꾸지 않는다(D-13)
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ChatPhotoCheck)
                .where(ChatPhotoCheck.status == "photo")
            )
            == 0
        )
