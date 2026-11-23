"""추억 후보 저장·조회(PR6): 일괄 자격·임베딩 조회(N+1 없음), 실제 임베딩·ImageStats 연결, 멱등 저장, 조회 때 재검증, 가족 격리, 정리 훅, 철회가 정리 실패에 막히지 않음.
후보는 비공개이고 자동 등록 경로는 없다(`refresh` 를 명시적으로 부를 때만 만들어진다). 사진은 합성 이미지, 임베딩은 합성 값이다."""

import io
import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import event, func, select, update

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_memory import (
    candidate_repository,
    candidate_service,
    discovery,
    encoder,
    reconcile,
    service,
)
from app.features.family_memory import embedding_repository as emb
from app.features.family_memory.models import (
    MemoryCandidate,
    MemoryCandidatePhoto,
    PhotoEmbedding,
)
from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.db import SessionLocal, engine

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
LEAVE = "/family-group/groups/me/leave"
DAY = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
DIM = 32


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    saved = (
        list(memory_hooks._member_withdrawn),
        list(memory_hooks._family_disabled),
        list(memory_hooks._photo_excluded),
        list(memory_hooks._attachment_removed),
    )
    yield
    memory_hooks._member_withdrawn[:] = saved[0]
    memory_hooks._family_disabled[:] = saved[1]
    memory_hooks._photo_excluded[:] = saved[2]
    memory_hooks._attachment_removed[:] = saved[3]


def _vec(topic_id: int, seed: str, noise: float = 0.5) -> tuple[float, ...]:
    base = random.Random(f"t{topic_id}")
    rng = random.Random(seed)
    unit = [base.gauss(0, 1) for _ in range(DIM)]
    norm = math.sqrt(sum(v * v for v in unit))
    return tuple(v / norm + rng.gauss(0, noise / math.sqrt(DIM)) for v in unit)


def _image(seed: int) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", (64, 48))
    img.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 48)]
    )
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


_counter = [0]


def _upload(client, headers, minutes: int | None, batch=None, room_id=None, day=DAY):
    from app.features.family_chat import photo_service as ps

    ps.upload_limiter._failures.clear()  # 시험이 많은 사진을 연달아 올린다
    _counter[0] += 1
    data = {}
    if minutes is not None:
        data["taken_at"] = (day + timedelta(minutes=minutes)).isoformat()
    if batch:
        data["batch_id"] = batch
    if room_id:
        data["room_id"] = room_id
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _image(_counter[0]), "image/jpeg")},
        data=data,
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


def _gid(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _store_embedding(att, group_id, user_id, vector):
    with SessionLocal() as db:
        emb.upsert(
            db,
            group_id,
            att,
            user_id,
            "siglip2-base-patch16-224",
            "test",
            len(vector),
            encoder.pack(list(vector)),
            datetime.now(UTC),
        )
        db.commit()


def _photos(client, headers, n, topic_id=1, start=0, **kw):
    """확인된 일반 사진 n 장(촬영 시각 5분 간격) + 그 합성 임베딩을 DB 에 저장한다."""
    gid, uid = _gid(client, headers), _uid(client, headers)
    made = []
    for i in range(n):
        att, msg = _upload(client, headers, start + i * 5, **kw)
        _confirm(att)
        _store_embedding(att, gid, uid, _vec(topic_id, att))
        made.append((att, msg))
    return made


def _discover(client, headers):
    with SessionLocal() as db:
        return discovery.discover_group(db, _gid(client, headers))


def _refresh(client, headers):
    with SessionLocal() as db:
        return candidate_service.refresh(db, _gid(client, headers))


def _rows(model):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def _api(client, headers):
    r = client.get(f"{BASE}/candidates", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---------- 실제 데이터 연결·N+1 ----------
def test_discover_group_uses_stored_embeddings_and_photo_files(client, family):
    a, _, _ = family
    _ready(client, a, a)
    morning = _photos(client, a, 4, topic_id=1, start=0)
    evening = _photos(
        client, a, 4, topic_id=2, start=180
    )  # 3시간 뒤 다른 장면(DB 의 임베딩으로만 갈린다)
    result = _discover(client, a)
    assert (result.considered, result.eligible, result.skipped) == (8, 8, {})
    assert len(result.candidates) == 2
    assert {frozenset(c.attachment_ids) for c in result.candidates} == {
        frozenset(m[0] for m in morning),
        frozenset(m[0] for m in evening),
    }
    assert set(result.uploaders.values()) == {_uid(client, a)}


def test_stats_come_from_the_stored_photo_file_and_unreadable_files_are_neutral(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made = _photos(client, a, 3)
    st = discovery.photo_stats(made[0][0])
    assert st is not None and len(st.content_hash) == 64 and 0 <= st.sharpness <= 1
    assert discovery.photo_stats("../../etc/passwd") is None  # 안전하지 않은 id
    from app.features.family_memory.analysis import photo_file

    photo_file(made[0][0]).unlink()
    assert discovery.photo_stats(made[0][0]) is None  # 파일이 없으면 화질 값 없이(중립) 계속한다
    assert len(_discover(client, a).candidates) == 1


def _count_statements(fn):
    counter = {"n": 0}

    def before(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return counter["n"]


def test_eligibility_and_embeddings_are_read_in_a_fixed_number_of_queries(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    gid = _gid(client, a)

    def run():
        with SessionLocal() as db:
            discovery.discover_group(db, gid)

    small = _count_statements(run)
    _photos(client, a, 20, start=300)
    large = _count_statements(run)
    assert small == large <= 8  # 사진이 4장에서 24장으로 늘어도 조회 수는 그대로(N+1 없음)


def test_batch_eligibility_matches_the_per_photo_check_for_every_state(client, family):
    a, b, _ = family
    _ready(client, a, a)  # b 는 동의하지 않음
    mine = []
    for status in ("photo", "pending", "unsure", "failed", "document"):
        att, _ = _upload(client, a, len(mine) * 5)
        _confirm(att, status)
        mine.append(att)
    excluded, _ = _upload(client, a, 60)
    _confirm(excluded)
    assert (
        client.put(
            f"{BASE}/photos/{excluded}/exclusion", json={"excluded": True}, headers=a
        ).status_code
        == 200
    )
    theirs, _ = _upload(client, b, 70)
    _confirm(theirs)
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    direct, _ = _upload(client, a, 80, room_id=room["id"])
    _confirm(direct)
    gid = _gid(client, a)
    with SessionLocal() as db:
        photos, batch = service.check_group_photos(db, gid)
        assert direct not in batch  # 1:1 사진은 조회에서 빠진다
        for p in photos:
            assert batch[p.attachment_id] == service.check_photo(db, p.attachment_id)
    assert {batch_v.reason for batch_v in batch.values()} >= {
        "ok",
        "not_confirmed_photo",
        "excluded",
        "no_consent",
    }


def test_missing_taken_at_is_never_replaced_by_the_upload_time(client, family):
    a, _, _ = family
    _ready(client, a, a)
    gid, uid = _gid(client, a), _uid(client, a)
    for _ in range(4):
        att, _ = _upload(client, a, None)
        _confirm(att)
        _store_embedding(att, gid, uid, _vec(1, att))
    assert _discover(client, a).candidates == []


# ---------- 멱등 저장 ----------
def test_refresh_stores_a_private_candidate_and_is_idempotent(client, family):
    a, _, group = family
    _ready(client, a, a)
    made = _photos(client, a, 5)
    first = _refresh(client, a)
    assert (first.created, first.updated, first.unchanged, first.removed) == (1, 0, 0, 0)
    with SessionLocal() as db:
        [row] = db.scalars(select(MemoryCandidate)).all()
        photos = db.scalars(select(MemoryCandidatePhoto)).all()
        assert (row.group_id, row.status, row.algorithm_version) == (
            group["id"],
            "private",
            "memgrp-1",
        )
        assert row.representative_id in {m[0] for m in made} and 0 < row.score <= 1
        assert {p.attachment_id for p in photos} == {m[0] for m in made}
        assert {p.user_id for p in photos} == {_uid(client, a)}
        stamp = row.updated_at
        cid = row.id
    again = _refresh(client, a)
    third = _refresh(client, a)
    assert (
        (again.created, again.updated, again.unchanged)
        == (0, 0, 1)
        == (third.created, third.updated, third.unchanged)
    )
    assert _rows(MemoryCandidate) == 1 and _rows(MemoryCandidatePhoto) == 5
    with SessionLocal() as db:
        row = db.get(MemoryCandidate, cid)
        assert row.updated_at == stamp  # 내용이 같으면 갱신 시각도 그대로


def test_refresh_replaces_a_candidate_when_its_photos_change_and_never_duplicates(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _refresh(client, a)
    with SessionLocal() as db:
        old_id = db.scalar(select(MemoryCandidate.id))
    _photos(client, a, 2, start=25)  # 같은 사건에 사진이 더 올라왔다
    result = _refresh(client, a)
    assert (result.created, result.removed) == (1, 1)
    with SessionLocal() as db:
        ids = db.scalars(select(MemoryCandidate.id)).all()
    assert len(ids) == 1 and ids[0] != old_id and _rows(MemoryCandidatePhoto) == 6


def test_refresh_is_deterministic_and_never_publishes(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 6)
    one, two = _discover(client, a), _discover(client, a)
    assert one.candidates == two.candidates
    _refresh(client, a)
    with SessionLocal() as db:
        assert set(db.scalars(select(MemoryCandidate.status))) == {"private"}


def test_refresh_clears_the_stored_candidates_when_nothing_is_eligible_any_more(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 1
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 0 and _rows(MemoryCandidatePhoto) == 0


# ---------- 조회 API ----------
def test_candidates_api_is_hidden_unless_released_and_needs_login(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", False)
    assert client.get(f"{BASE}/candidates", headers=a).status_code == 404  # 미출시 가드
    monkeypatch.setattr(settings, "family_memory_candidates_api_enabled", True)
    assert client.get(f"{BASE}/candidates").status_code in (401, 403)  # 인증 필요
    assert _api(client, a) == []


def test_candidates_api_returns_the_contract_for_the_current_family_only(
    client, family, other_family
):
    a, b, group = family
    _ready(client, a, a)
    made = _photos(client, a, 5)
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=other_family).status_code
        == 200
    )
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=other_family).status_code
        == 200
    )
    theirs = _photos(client, other_family, 4)
    _refresh(client, a)
    _refresh(client, other_family)
    items = _api(client, a)
    assert len(items) == 1
    item = items[0]
    assert set(item) == {
        "id", "status", "representative", "photos", "photo_count", "dated_count", "undated_count",
        "starts_at", "ends_at", "bridged", "score", "algorithm_version", "updated_at",
    }  # fmt: skip
    assert item["status"] == "private" and item["photo_count"] == 5 == len(item["photos"])
    assert {p["attachment_id"] for p in item["photos"]} == {m[0] for m in made}
    assert item["representative"]["is_representative"] is True
    assert item["representative"]["thumb_url"] == (
        f"/family-chat/photos/{item['representative']['attachment_id']}?size=thumb"
    )
    assert sum(p["is_representative"] for p in item["photos"]) == 1
    assert item["dated_count"] == 5 and item["undated_count"] == 0 and item["starts_at"]
    other = _api(client, other_family)  # 다른 가족은 자기 후보만 본다
    assert len(other) == 1 and {p["attachment_id"] for p in other[0]["photos"]} == {
        t[0] for t in theirs
    }
    assert all(m[0] not in str(other) for m in made)
    # 같은 가족의 동의하지 않은 구성원도 볼 수는 있다(가족 사진은 채팅에서 이미 함께 보는 것이고 분석 자격은 올린 사람 기준)
    assert len(_api(client, b)) == 1 and group["id"]


# ---------- 조회 때 재검증 ----------
def test_ineligible_photos_vanish_from_the_response_with_their_metadata(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made = _photos(client, a, 6)
    _refresh(client, a)
    gone = made[0][0]
    # 훅이 닿지 않은 경우를 가정: 판별 상태를 바꿔 자격만 잃게 한다(저장본은 그대로)
    _confirm(gone, "unsure")
    [item] = _api(client, a)
    assert gone not in {p["attachment_id"] for p in item["photos"]} and item["photo_count"] == 5
    assert gone not in str(item)  # 주소·id 어디에도 없다
    with SessionLocal() as db:
        gone_taken = db.execute(
            select(ChatPhotoCheck.attachment_id).where(ChatPhotoCheck.attachment_id == gone)
        ).first()
        assert gone_taken
    times = sorted(p["taken_at"] for p in item["photos"])
    assert (
        item["starts_at"] == times[0] and item["ends_at"] == times[-1]
    )  # 시각 범위는 남은 사진으로 다시 계산


def test_representative_is_reselected_when_it_becomes_invalid(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 6)
    _refresh(client, a)
    [before] = _api(client, a)
    rep = before["representative"]["attachment_id"]
    _confirm(rep, "document")  # 대표 사진이 문서로 바뀌어 자격을 잃었다
    [after] = _api(client, a)
    new_rep = after["representative"]["attachment_id"]
    assert new_rep != rep and new_rep in {p["attachment_id"] for p in after["photos"]}
    assert rep not in str(after)
    assert sum(p["is_representative"] for p in after["photos"]) == 1


def test_candidate_is_hidden_when_fewer_than_three_scenes_remain(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made = _photos(client, a, 4)
    _refresh(client, a)
    assert len(_api(client, a)) == 1
    _confirm(made[0][0], "unsure")
    _confirm(made[1][0], "unsure")  # 2장면만 남는다(PR5 최소 크기 3)
    assert _api(client, a) == []


def test_family_or_server_switch_off_hides_everything(client, family, monkeypatch):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _refresh(client, a)
    assert len(_api(client, a)) == 1
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    assert _api(client, a) == []
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    assert _api(client, a) == []


# ---------- 정리 훅과 대조 정리 ----------
def test_withdrawal_exclusion_deletion_and_family_off_remove_the_stored_candidates(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made = _photos(client, a, 4)
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 1
    assert (
        client.put(
            f"{BASE}/photos/{made[0][0]}/exclusion", json={"excluded": True}, headers=a
        ).status_code
        == 200
    )
    assert (
        _rows(MemoryCandidate) == 0 and _rows(MemoryCandidatePhoto) == 0
    )  # 제외한 사진이 든 후보는 통째로 사라진다
    client.put(f"{BASE}/photos/{made[0][0]}/exclusion", json={"excluded": False}, headers=a)
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 1
    assert client.delete(f"{MSG}/{made[1][1]}", headers=a).status_code == 200
    assert _rows(MemoryCandidate) == 0  # 사진을 지우면 그 사진이 든 후보도 지워진다
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 1
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert _rows(MemoryCandidate) == 0  # 철회
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    _refresh(client, a)
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    assert _rows(MemoryCandidate) == 0  # 가족 끄기


def test_leaving_the_family_removes_candidates_with_that_members_photos_only(client, family):
    a, b, _ = family
    _ready(client, a, a)
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=b).status_code == 200
    _photos(client, a, 4, start=0)
    _photos(client, b, 4, topic_id=2, start=300)  # 5시간 뒤 다른 장면: b 의 사진으로 따로 묶인다
    _refresh(client, a)
    assert _rows(MemoryCandidate) == 2
    assert client.post(LEAVE, headers=b).status_code in (200, 204)
    assert _rows(MemoryCandidate) == 1
    with SessionLocal() as db:
        assert set(db.scalars(select(MemoryCandidatePhoto.user_id))) == {_uid(client, a)}


def test_withdrawal_is_accepted_even_if_candidate_cleanup_fails_and_nothing_is_exposed(
    client, family, monkeypatch
):
    """PR6 안전성: 후보 정리가 실패해도 철회는 수락된다. 남은 후보는 조회 때 재검증으로 보이지 않고, 대조 정리가 멱등하게 지운다."""
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _refresh(client, a)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(candidate_repository, "candidate_ids_with_photos", boom)
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    assert (
        client.get(f"{BASE}/settings", headers=a).json()["me"]["consented"] is False
    )  # 철회가 유지된다
    assert _rows(MemoryCandidate) == 1  # 정리는 실패해 후보가 남았지만
    assert _api(client, a) == []  # 조회 때 자격 재검증으로 아무것도 보이지 않는다
    monkeypatch.undo()
    with SessionLocal() as db:
        result = reconcile.reconcile(db)
        db.commit()
        assert result.candidates == 1
        assert reconcile.reconcile(db).total == 0  # 멱등
    assert _rows(MemoryCandidate) == 0 and _rows(MemoryCandidatePhoto) == 0


def test_reconcile_removes_embeddings_candidates_and_jobs_without_consent_only(client, family):
    a, b, _ = family
    _ready(client, a, a)
    made = _photos(client, a, 4)
    _refresh(client, a)
    gid = _gid(client, a)
    _store_embedding(made[0][0], gid, _uid(client, a), _vec(1, "x"))
    with SessionLocal() as db:
        assert reconcile.reconcile(db).total == 0  # 동의가 유효하면 아무것도 지우지 않는다
        # 동의 행을 직접 철회 상태로 만든다(훅이 없던 경로)
        from app.features.family_memory.models import MemberMemoryConsent

        db.get(MemberMemoryConsent, (gid, _uid(client, a))).withdrawn_at = datetime.now(UTC)
        db.commit()
        result = reconcile.reconcile(db)
        db.commit()
        assert result.embeddings == 4 and result.candidates == 1
    assert _rows(PhotoEmbedding) == 0 and b


def test_chat_and_other_family_data_are_untouched_by_candidates(client, family, other_family):
    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=other_family).status_code
        == 200
    )
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=other_family).status_code
        == 200
    )
    _photos(client, other_family, 4)
    _refresh(client, a)
    _refresh(client, other_family)
    assert _rows(MemoryCandidate) == 2
    assert (
        client.put(f"{BASE}/consent", json={"consent": False}, headers=other_family).status_code
        == 200
    )
    assert _rows(MemoryCandidate) == 1  # 다른 가족의 철회는 우리 후보를 건드리지 않는다
    assert len(_api(client, a)) == 1
    assert (
        client.get("/family-chat/timeline/photos", headers=a).status_code == 200
    )  # 기존 타임라인은 그대로


def test_worker_reconcile_deletes_leftovers_and_never_raises(client, family, monkeypatch):
    from app.features.family_memory import worker

    a, _, _ = family
    _ready(client, a, a)
    _photos(client, a, 4)
    _refresh(client, a)
    with SessionLocal() as db:  # 훅이 닿지 않은 경로: 동의 행만 철회 상태로 만든다
        from app.features.family_memory.models import MemberMemoryConsent

        db.get(MemberMemoryConsent, (_gid(client, a), _uid(client, a))).withdrawn_at = datetime.now(
            UTC
        )
        db.commit()
    assert _rows(MemoryCandidate) == 1 and _rows(PhotoEmbedding) == 4
    assert worker.reconcile_derived() == 5  # 후보 1 + 임베딩 4
    assert _rows(MemoryCandidate) == 0 and _rows(PhotoEmbedding) == 0
    assert worker.reconcile_derived() == 0  # 멱등

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(reconcile, "reconcile", boom)
    assert worker.reconcile_derived() == 0  # 실패해도 루프가 멈추지 않는다
