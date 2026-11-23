"""추억 후보 발견(PR5) 통합 시험: 자격(PR1 `check_photo`)을 통과한 사진만 그룹화에 넘어가는지, 동의 철회·삭제·제외·1:1·문서·가족 격리가 후보를 바로 막는지 본다.
임베딩은 합성 값을 주입하고 DB 에는 아무것도 저장하지 않는다(요청할 때마다 계산)."""

import io
import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import update

from app.features.family_chat.models import ChatPhotoCheck
from app.features.family_memory import discovery
from app.shared.config import settings
from app.shared.db import SessionLocal

BASE = "/family-memory"
PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
DIM = 32
DAY = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "family_memory_enabled", True)


def _vec(topic_id: int, seed: str, noise: float = 0.5) -> tuple[float, ...]:
    base = random.Random(f"t{topic_id}")
    rng = random.Random(seed)
    unit = [base.gauss(0, 1) for _ in range(DIM)]
    norm = math.sqrt(sum(v * v for v in unit))
    return tuple(v / norm + rng.gauss(0, noise / math.sqrt(DIM)) for v in unit)


def _upload(client, headers, minutes: int | None, batch=None, room_id=None, day=DAY):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    data = {}
    if minutes is not None:
        data["taken_at"] = (day + timedelta(minutes=minutes)).isoformat()
    if batch:
        data["batch_id"] = batch
    if room_id:
        data["room_id"] = room_id
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, data=data, headers=headers
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


def _group_id(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _photos(client, headers, n, topic_id=1, start=0, **kw):
    """확인된 일반 사진 n 장(촬영 시각 5분 간격)과 그 합성 임베딩."""
    made, emb = [], {}
    for i in range(n):
        att, msg = _upload(client, headers, start + i * 5, **kw)
        _confirm(att)
        emb[att] = _vec(topic_id, att)
        made.append((att, msg))
    return made, emb


def _discover(client, headers, embeddings):
    with SessionLocal() as db:
        return discovery.discover(db, _group_id(client, headers), embeddings.get)


def test_eligible_photos_form_a_candidate_with_the_required_output(client, family):
    a, _, group = family
    _ready(client, a, a)
    made, emb = _photos(client, a, 5)
    result = _discover(client, a, emb)
    assert (result.considered, result.eligible, result.skipped) == (5, 5, {})
    [c] = result.candidates
    assert c.group_id == group["id"] and sorted(c.attachment_ids) == sorted(m[0] for m in made)
    assert c.representative_id in c.attachment_ids and c.algorithm_version == "memgrp-1"
    assert c.time_evidence.basis == "taken_at" and 0 < c.score <= 1


def test_discovery_only_reads_and_stores_nothing(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _, emb = _photos(client, a, 4)
    with SessionLocal() as db:
        discovery.discover(db, _group_id(client, a), emb.get)
        assert (
            not db.new and not db.dirty and not db.deleted
        )  # 읽기만 한다: 저장·작업 등록 경로 없음


# ---------- 8. 미동의·철회·제외, 서버·가족 설정 ----------
def test_unconsented_members_photos_are_skipped_and_only_consenting_uploaders_count(client, family):
    a, b, _ = family
    _ready(client, a, a)  # b 는 동의하지 않았다
    mine, emb = _photos(client, a, 3)
    theirs, emb_b = _photos(client, b, 3, start=100)
    result = _discover(client, a, {**emb, **emb_b})
    assert result.skipped == {"no_consent": 3} and result.eligible == 3
    [c] = result.candidates
    assert set(c.attachment_ids) == {m[0] for m in mine}


def test_withdrawal_removes_the_photos_from_candidates_immediately(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _, emb = _photos(client, a, 4)
    assert len(_discover(client, a, emb).candidates) == 1
    assert client.put(f"{BASE}/consent", json={"consent": False}, headers=a).status_code == 200
    result = _discover(client, a, emb)
    assert result.candidates == [] and result.eligible == 0 and result.skipped == {"no_consent": 4}
    assert client.put(f"{BASE}/consent", json={"consent": True}, headers=a).status_code == 200
    assert len(_discover(client, a, emb).candidates) == 1  # 재동의하면 다시 후보에 들어간다


def test_per_photo_exclusion_and_deletion_drop_the_photo(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made, emb = _photos(client, a, 5)
    first = _discover(client, a, emb).candidates[0]
    excluded = made[0][0]
    r = client.put(f"{BASE}/photos/{excluded}/exclusion", json={"excluded": True}, headers=a)
    assert r.status_code == 200
    second = _discover(client, a, emb)
    assert excluded not in second.candidates[0].attachment_ids and second.skipped == {"excluded": 1}
    assert client.delete(f"{MSG}/{made[1][1]}", headers=a).status_code == 200
    third = _discover(client, a, emb).candidates[0]
    assert made[1][0] not in third.attachment_ids and len(third.attachment_ids) == 3
    assert third.candidate_id != first.candidate_id


def test_family_off_and_server_off_give_no_candidates(client, family, monkeypatch):
    a, _, _ = family
    _ready(client, a, a)
    _, emb = _photos(client, a, 4)
    assert client.put(f"{BASE}/settings", json={"enabled": False}, headers=a).status_code == 200
    assert _discover(client, a, emb).candidates == []
    assert client.put(f"{BASE}/settings", json={"enabled": True}, headers=a).status_code == 200
    assert len(_discover(client, a, emb).candidates) == 1
    monkeypatch.setattr(settings, "family_memory_enabled", False)
    result = _discover(client, a, emb)
    assert result.candidates == [] and result.skipped == {"server_off": 4}


# ---------- 9. 문서·미확인·1:1 ----------
def test_unconfirmed_document_and_one_to_one_photos_are_blocked(client, family):
    a, b, _ = family
    _ready(client, a, a)
    good, emb = _photos(client, a, 3)
    emb_extra = {}
    for status in ("pending", "unsure", "failed", "document"):
        att, _ = _upload(client, a, 60 + len(emb_extra) * 5)
        _confirm(att, status)
        emb_extra[att] = _vec(1, att)
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    direct, _ = _upload(client, a, 10, room_id=room["id"])
    _confirm(direct)
    emb_extra[direct] = _vec(1, direct)
    result = _discover(client, a, {**emb, **emb_extra})
    assert result.skipped == {
        "not_confirmed_photo": 4
    }  # 1:1 사진은 후보 조회에 아예 들어오지 않는다
    assert result.considered == 7 and result.eligible == 3
    [c] = result.candidates
    assert set(c.attachment_ids) == {m[0] for m in good}


def test_automatic_ai_judgement_never_promotes_unsure_to_photo_here(client, family):
    a, _, _ = family
    _ready(client, a, a)
    att, _ = _upload(client, a, 0)
    _confirm(att, "unsure")
    _discover(client, a, {att: _vec(1, att)})
    with SessionLocal() as db:
        assert (
            db.get(ChatPhotoCheck, att).status == "unsure"
        )  # D-13: 발견은 판별 상태를 읽기만 한다


# ---------- 7. 가족 격리 ----------
def test_other_family_photos_are_never_mixed(client, family, other_family):
    a, _, group = family
    _ready(client, a, a)
    mine, emb = _photos(client, a, 4)
    assert (
        client.put(f"{BASE}/settings", json={"enabled": True}, headers=other_family).status_code
        == 200
    )
    assert (
        client.put(f"{BASE}/consent", json={"consent": True}, headers=other_family).status_code
        == 200
    )
    theirs, emb_o = _photos(client, other_family, 4)  # 같은 시각·같은 장면(임베딩 주제)
    both = {**emb, **emb_o}
    mine_result = _discover(client, a, both)
    theirs_result = _discover(client, other_family, both)
    assert {i for c in mine_result.candidates for i in c.attachment_ids} == {m[0] for m in mine}
    assert {i for c in theirs_result.candidates for i in c.attachment_ids} == {t[0] for t in theirs}
    assert mine_result.group_id == group["id"] != theirs_result.group_id


# ---------- 10. 빈 결과, 날짜·연도, batch ----------
def test_too_few_eligible_photos_give_an_empty_result(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _, emb = _photos(client, a, 2)
    result = _discover(client, a, emb)
    assert result.candidates == [] and result.eligible == 2


def test_photos_without_taken_at_do_not_form_a_group_and_same_scene_years_apart_split(
    client, family
):
    a, _, _ = family
    _ready(client, a, a)
    undated, emb = [], {}
    for _ in range(4):
        att, _ = _upload(client, a, None, batch="upload-batch-1")
        _confirm(att)
        emb[att] = _vec(1, att)
        undated.append(att)
    assert _discover(client, a, emb).candidates == []  # 업로드 시각을 촬영 시각으로 쓰지 않는다
    old, emb_old = [], {}
    for i in range(4):
        att, _ = _upload(client, a, i * 5, day=DAY - timedelta(days=400))
        _confirm(att)
        emb_old[att] = _vec(1, att)
        old.append(att)
    new, emb_new = _photos(client, a, 4)
    result = _discover(client, a, {**emb, **emb_old, **emb_new})
    assert len(result.candidates) == 2  # 400일 간격의 같은 장면은 다른 후보
    assert {c.time_evidence.start.year for c in result.candidates} == {2023, 2024}


def test_missing_embeddings_fall_back_to_time_evidence_only(client, family):
    a, _, _ = family
    _ready(client, a, a)
    made, _ = _photos(client, a, 4)
    [c] = _discover(client, a, {}).candidates  # 임베딩 조회가 비어 있어도 시간 근거로 묶는다
    assert set(c.attachment_ids) == {m[0] for m in made}


def test_discovery_is_deterministic_across_calls(client, family):
    a, _, _ = family
    _ready(client, a, a)
    _, emb = _photos(client, a, 6)
    assert _discover(client, a, emb).candidates == _discover(client, a, emb).candidates
