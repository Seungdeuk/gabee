"""가족 타임라인 MVP(2026-11-26): 로컬 SigLIP2 분석으로 자동 후보를 만들고(문서 margin > 5 는 제외), 같은 날 비슷한 사진을 묶고, 업로더가 뺀 사진은 다시 나오지 않는다.

분석 함수는 대역(`shared/image_features`)이라 실제 모델·외부 호출이 없다. 임베딩은 시험이 직접 만든 단위 벡터다.
이 시험은 분류·묶기의 정확도를 평가하지 않는다: 규칙이 설계대로 동작하는지만 본다."""

import io
import threading
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest
from PIL import Image

from app.features.family_chat import photo_check_service as pcs
from app.features.family_chat import photo_service as ps
from app.features.family_chat import timeline_features as tf
from app.features.family_chat import timeline_grouping as tg
from app.features.family_chat.models import ChatPhotoCheck, MessageAttachment
from app.shared import chat_library, image_features, photo_analysis_consent
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

_REAL_SCHEDULE = tf.schedule  # 루트 conftest 가 시험마다 `schedule` 을 아무것도 안 하는 함수로 바꾸므로, 진짜 함수를 붙잡아 둔다
PHOTOS = "/family-chat/photos"
TIMELINE = "/family-chat/timeline/photos"
BASE_DAY = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)  # 한국 시간 12:00
RNG = np.random.default_rng(11)


def unit(v) -> list[float]:
    v = np.asarray(v, dtype=np.float64)
    return list((v / np.linalg.norm(v)).astype(float))


BASE = RNG.normal(size=768)
OTHER = RNG.normal(size=768)


def similar_to(base, noise=0.15):
    return unit(
        np.asarray(base) / np.linalg.norm(base) + RNG.normal(size=768) * noise / np.sqrt(768)
    )


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ps.library_limiter._failures.clear()
    pcs.check_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("외부 AI 를 부르면 안 돼요(타임라인 분류·묶기는 로컬 모델만)")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(chat_library, "_on_photo", None)
    monkeypatch.setattr(chat_library, "_is_registered", lambda db, g, a: False)
    # 이 모듈은 자동 후보·유사 묶기 동작 자체를 본다: 서버 스위치를 켜고(기본은 꺼짐, ADR 0026) ADR 0020 조건은 모두 만족한 것으로 둔다.
    # 기본 꺼짐·동의 조건·철회 정리는 test_timeline_policy_switch.py 가 실제 조건으로 시험한다.
    monkeypatch.setattr(settings, "timeline_auto_candidates", True)
    monkeypatch.setattr(
        photo_analysis_consent, "_checker", lambda db, group_id, uploaders: set(uploaders)
    )
    previous = image_features._analyzer
    tf._cache.clear()
    tf._inflight.clear()
    tf._revoked.clear()
    yield
    image_features.register_analyzer(previous)
    tf._cache.clear()
    tf._inflight.clear()
    tf._revoked.clear()


def _jpeg(color=(10, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="JPEG")
    return out.getvalue()


def _send(client, headers, batch_id=None, judged: str | None = "unsure") -> str:
    """사진을 올린다. 문서함 판별이 끝나 애매(`unsure`, 자동)로 적힌 상태로 둔다(SigLIP2 단독 판별에서 문서가 아닌 사진의 결과).
    타임라인 자동 분석 범위는 판별이 끝난 unsure 뿐이다(ADR 0026). `judged=None` 이면 방금 올린 대기(pending) 상태 그대로 둔다."""
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data={"batch_id": batch_id} if batch_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]["id"]
    if judged is not None:
        _status_set(att, judged)
    return att


def _status_set(att: str, status: str, source: str = "auto") -> None:
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = status, source
        db.commit()


def _taken(att, when: datetime) -> None:
    with SessionLocal() as db:
        db.get(MessageAttachment, att).taken_at = when
        db.commit()


def _put(att, margin, embedding) -> None:
    """분석이 끝난 것처럼 결과 파일을 둔다(실제 저장 형식 그대로)."""
    import json

    tf._write_atomic(
        tf._sig_path(att),
        json.dumps({"v": 1, "margin": margin, "emb": [round(v, 5) for v in embedding]}),
    )
    tf._cache.pop(att, None)


def _timeline(client, headers, **params):
    r = client.get(TIMELINE, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _status(att) -> ChatPhotoCheck:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, att)


def _candidate(client, headers, when, emb=None, margin=0.0, batch_id=None) -> str:
    att = _send(client, headers, batch_id)
    _taken(att, when)
    _put(att, margin, emb if emb is not None else unit(RNG.normal(size=768)))
    return att


# ---------- 1·2 후보와 문서 제외 ----------
def test_an_ordinary_photo_is_a_timeline_candidate_without_any_confirmation(client, family):
    a, _, _ = family
    att = _candidate(client, a, BASE_DAY, margin=-3.0)
    body = _timeline(client, a)
    assert [i["attachment_id"] for i in body["items"]] == [att]
    item = body["items"][0]
    assert item["confirmed"] is False and item["group_kind"] == "single" and item["mine"] is True
    assert _status(att).status in ("pending", "unsure")  # 판별 상태(문서함 쪽)는 바꾸지 않는다


@pytest.mark.parametrize("margin", [5.01, 9.0])
def test_a_document_photo_is_not_an_automatic_candidate(client, family, margin):
    a, _, _ = family
    _candidate(client, a, BASE_DAY, margin=margin)
    body = _timeline(client, a)
    assert body["items"] == [] and body["analyzing"] == 0 and body["analysis_failed"] == 0


def test_margin_exactly_five_is_still_a_candidate(client, family):
    a, _, _ = family
    att = _candidate(
        client, a, BASE_DAY, margin=5.0
    )  # margin > 5 만 문서 후보(기존 규칙과 같은 경계)
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [att]


# ---------- 3·4·5 묶기 ----------
def test_similar_photos_on_the_same_day_are_grouped_with_a_server_group_id(client, family):
    a, _, _ = family
    ids = [
        _candidate(client, a, BASE_DAY + timedelta(minutes=m), emb=similar_to(BASE))
        for m in (0, 5, 30)
    ]
    items = _timeline(client, a)["items"]
    assert {i["attachment_id"] for i in items} == set(ids)
    assert {i["group_kind"] for i in items} == {"similar"}
    keys = {i["batch_id"] for i in items}
    assert len(keys) == 1 and next(iter(keys)).startswith("s_")  # 서버가 만든 묶음 번호
    assert len({i["display_at"] for i in items}) == 1  # 묶음은 가장 이른 시각 한 자리에 모인다


def test_same_looking_photos_on_different_days_are_never_merged(client, family):
    a, _, _ = family
    day1 = _candidate(client, a, BASE_DAY, emb=similar_to(BASE))
    day2 = _candidate(client, a, BASE_DAY + timedelta(days=3), emb=similar_to(BASE))
    items = {i["attachment_id"]: i for i in _timeline(client, a)["items"]}
    assert items[day1]["group_kind"] == items[day2]["group_kind"] == "single"
    assert items[day1]["batch_id"] != items[day2]["batch_id"] or items[day1]["batch_id"] is None


def test_similar_photos_far_apart_in_the_same_day_are_not_merged(client, family):
    a, _, _ = family
    morning = _candidate(client, a, BASE_DAY - timedelta(hours=2), emb=similar_to(BASE))
    evening = _candidate(
        client, a, BASE_DAY + timedelta(hours=6), emb=similar_to(BASE)
    )  # 같은 한국 날짜, 8시간 차이
    items = {i["attachment_id"]: i for i in _timeline(client, a)["items"]}
    assert items[morning]["group_kind"] == items[evening]["group_kind"] == "single"


def test_a_photo_without_similar_ones_is_shown_alone_next_to_a_group(client, family):
    a, _, _ = family
    group = [
        _candidate(client, a, BASE_DAY + timedelta(minutes=m), emb=similar_to(BASE)) for m in (0, 3)
    ]
    alone = _candidate(client, a, BASE_DAY + timedelta(minutes=10), emb=unit(OTHER))
    items = {i["attachment_id"]: i for i in _timeline(client, a)["items"]}
    assert items[alone]["group_kind"] == "single"
    assert all(items[g]["group_kind"] == "similar" for g in group)


def test_the_upload_batch_stays_one_card_and_never_joins_similar_photos(client, family):
    a, _, _ = family
    b1 = _candidate(client, a, BASE_DAY, emb=unit(OTHER), batch_id="batchaaaa1")
    b2 = _candidate(client, a, BASE_DAY, emb=unit(RNG.normal(size=768)), batch_id="batchaaaa1")
    twin = _candidate(
        client, a, BASE_DAY, emb=unit(OTHER)
    )  # 업로드 묶음 b1 과 거의 같은 사진을 따로 올렸다
    items = {i["attachment_id"]: i for i in _timeline(client, a)["items"]}
    assert items[b1]["batch_id"] == items[b2]["batch_id"] == "batchaaaa1"
    assert items[b1]["group_kind"] == items[b2]["group_kind"] == "batch"
    assert items[twin]["group_kind"] == "single"  # 업로드 묶음과 이어 붙이지 않는다


# ---------- 6·7 제외 ----------
def test_an_excluded_candidate_never_comes_back_even_after_reanalysis_and_restart(client, family):
    a, _, _ = family
    keep = _candidate(client, a, BASE_DAY, emb=unit(OTHER))
    gone = _candidate(client, a, BASE_DAY + timedelta(minutes=1), emb=similar_to(BASE))
    assert {i["attachment_id"] for i in _timeline(client, a)["items"]} == {keep, gone}
    r = client.post(f"{PHOTOS}/{gone}/exclude", headers=a)
    assert r.status_code == 200 and r.json() == {"status": "excluded", "source": "manual"}
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [keep]
    # 다시 분석하고(결과 파일을 새로 쓰고) 메모리 캐시를 비워도(서버 재시작) 제외는 DB 에 남아 있다
    _put(gone, -2.0, similar_to(BASE))
    tf._cache.clear()
    tf._inflight.clear()
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [keep]
    # 제외는 타임라인 선택(이력 줄)으로 남고, 자동 판별 줄(문서함 판정)은 바꾸지 않는다(ADR 0026: 타임라인 상태는 판정을 바꾸지 않는다)
    assert (_status(gone).status, _status(gone).source) == ("unsure", "auto")


def test_only_the_uploader_can_exclude_and_members_cannot_hide_others_photos(client, family):
    a, b, _ = family
    att = _candidate(client, a, BASE_DAY)
    assert client.post(f"{PHOTOS}/{att}/exclude", headers=b).status_code == 404
    assert [i["attachment_id"] for i in _timeline(client, b)["items"]] == [
        att
    ]  # 다른 구성원도 볼 수 있다(같은 가족방)
    assert _timeline(client, b)["items"][0]["mine"] is False


def test_an_unanalyzed_photo_cannot_be_excluded_because_it_is_not_in_the_timeline(client, family):
    a, _, _ = family
    att = _send(client, a)  # 분석 결과 없음
    r = client.post(f"{PHOTOS}/{att}/exclude", headers=a)
    assert r.status_code == 409 and r.json()["code"] == "not_in_timeline"


# ---------- 8 가족 경계 ----------
def test_another_family_cannot_see_or_exclude_these_photos(client, family, other_family):
    a, _, _ = family
    att = _candidate(client, a, BASE_DAY)
    assert _timeline(client, other_family)["items"] == []
    assert client.post(f"{PHOTOS}/{att}/exclude", headers=other_family).status_code == 404
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [att]


# ---------- 9 분석 실패·분석 전 ----------
def test_analysis_failure_is_not_a_candidate_is_counted_and_the_timeline_still_works(
    client, family, monkeypatch
):
    a, _, _ = family
    ok = _candidate(client, a, BASE_DAY, margin=-1.0)
    broken = _send(client, a)

    def fail(data):
        raise RuntimeError("secret detail that must not be recorded")

    image_features.register_analyzer(fail)
    assert tf.analyze_attachment(broken) is False
    bad = tf.failure(broken)
    assert bad is not None and bad[0] == "RuntimeError"  # 종류 이름만 남는다(메시지 내용은 아니다)
    body = _timeline(client, a)
    assert [i["attachment_id"] for i in body["items"]] == [ok]
    assert body["analysis_failed"] == 1 and body["analyzing"] == 0


def test_a_failed_analysis_is_retried_after_the_wait_and_recovers(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    image_features.register_analyzer(lambda d: (_ for _ in ()).throw(RuntimeError("x")))
    tf.analyze_attachment(att)
    scheduled = []
    monkeypatch.setattr(tf, "schedule", lambda ids: scheduled.append(list(ids)) or len(scheduled))
    _timeline(client, a)
    assert scheduled == []  # 아직 기다리는 중: 다시 맡기지 않는다
    monkeypatch.setattr(tf, "RETRY_FAILED_AFTER", 0.0)
    _timeline(client, a)
    assert scheduled == [[att]]  # 시간이 지나 다시 맡긴다
    image_features.register_analyzer(lambda d: (-2.0, unit(BASE)))  # 모델이 준비됐다
    assert tf.analyze_attachment(att) is True and tf.failure(att) is None  # 실패 기록은 지워진다
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [att]


def test_without_any_analyzer_the_timeline_keeps_only_confirmed_photos(client, family):
    a, _, _ = family
    image_features.register_analyzer(None)  # 모델이 없는 서버(기본 상태)
    plain = _send(client, a)
    confirmed = _send(client, a)
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, confirmed)
        row.status, row.source = "photo", "manual"
        db.commit()
    tf.analyze_attachment(plain)
    body = _timeline(client, a)
    assert [i["attachment_id"] for i in body["items"]] == [
        confirmed
    ]  # 기존 동작: 직접 확인한 사진만
    assert body["analysis_failed"] == 1


def test_pending_unanalyzed_photos_are_counted_but_not_shown(client, family):
    a, _, _ = family
    _send(client, a)
    _send(client, a)
    body = _timeline(client, a)
    assert body["items"] == [] and body["analyzing"] == 2


# ---------- 분석 파이프라인·캐시·처리량 ----------
def test_analysis_runs_once_per_photo_and_the_result_is_cached(client, family):
    a, _, _ = family
    calls = []

    def analyzer(data):
        calls.append(len(data))
        return -1.5, unit(BASE)

    image_features.register_analyzer(analyzer)
    att = _send(client, a)
    assert tf.analyze_attachment(att) is True
    saved = tf.load(att)
    assert saved is not None and saved.margin == -1.5 and len(saved.embedding) == 768
    for _ in range(3):
        assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [att]
    assert len(calls) == 1  # 조회를 반복해도 추론은 다시 하지 않는다


def test_a_missing_original_is_a_recorded_failure_not_a_crash(client, family):
    a, _, _ = family
    att = _send(client, a)
    (tf._dir() / f"{att}.jpg").unlink()
    assert tf.analyze_attachment(att) is False
    assert tf.failure(att)[0] == "OriginalMissing"


def test_a_timeline_request_hands_over_a_bounded_number_of_photos(client, family, monkeypatch):
    a, _, _ = family
    for _ in range(tf.BACKFILL_PER_REQUEST + 5):
        ps.upload_limiter._failures.clear()  # 시험 준비용 업로드가 속도 제한에 걸리지 않게(상한 검증과 무관)
        _send(client, a)
    seen = []
    monkeypatch.setattr(tf, "schedule", lambda ids: seen.append(list(ids)) or 0)
    _timeline(client, a)
    assert (
        len(seen) == 1 and len(seen[0]) == tf.BACKFILL_PER_REQUEST
    )  # 요청 한 번에 무제한 분석을 맡기지 않는다


def test_two_overlapping_timeline_requests_still_fit_in_the_queue():
    assert tf.BACKFILL_PER_REQUEST * 2 <= tf.MAX_QUEUE


# ---------- 영속성: 재시작·캐시 소실·원본 소실 (영속 저장소가 없으면 보장하지 못하는 범위도 그대로 드러낸다) ----------
def test_results_survive_a_restart_and_unanalyzed_photos_are_handed_over_again(
    client, family, monkeypatch
):
    a, _, _ = family
    calls = []
    image_features.register_analyzer(lambda data: (calls.append(1), (-2.0, unit(BASE)))[1])
    done, waiting = _send(client, a), _send(client, a)
    assert tf.analyze_attachment(done) is True
    # 서버 재시작: 메모리(캐시·진행 중 목록)는 사라지고 디스크의 파일만 남는다
    tf._cache.clear()
    tf._inflight.clear()
    seen = []
    monkeypatch.setattr(tf, "schedule", lambda ids: seen.append(list(ids)) or 0)
    body = _timeline(client, a)
    assert [i["attachment_id"] for i in body["items"]] == [
        done
    ]  # 끝난 분석은 다시 하지 않고 그대로 보인다
    assert len(calls) == 1
    assert seen == [[waiting]]  # 아직 안 한 사진만 다시 맡긴다


def test_a_lost_cache_is_rebuilt_from_the_original(client, family):
    a, _, _ = family
    calls = []
    image_features.register_analyzer(lambda data: (calls.append(1), (-2.0, unit(BASE)))[1])
    att = _send(client, a)
    assert tf.analyze_attachment(att) is True
    tf._sig_path(att).unlink()  # 인스턴스 교체로 캐시 파일만 사라졌다(원본은 남아 있다)
    tf._cache.clear()
    assert _timeline(client, a)["items"] == []  # 잠깐은 정리 중
    assert tf.analyze_attachment(att) is True
    assert [i["attachment_id"] for i in _timeline(client, a)["items"]] == [att]
    assert len(calls) == 2


def test_when_the_original_is_gone_too_the_user_sees_a_not_organized_count_not_a_wrong_photo(
    client, family
):
    a, _, _ = family
    image_features.register_analyzer(lambda data: (-2.0, unit(BASE)))
    att = _send(client, a)
    (tf._dir() / f"{att}.jpg").unlink()  # 원본과 캐시가 모두 없는 인스턴스(영속 저장소 없음)
    assert tf.analyze_attachment(att) is False
    body = _timeline(client, a)
    assert body["items"] == [] and body["analysis_failed"] == 1 and body["analyzing"] == 0


def test_the_analysis_queue_is_bounded(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(tf, "schedule", _REAL_SCHEDULE)
    monkeypatch.setattr(tf, "MAX_QUEUE", 2)
    monkeypatch.setattr(tf, "_run", lambda att: gate.wait(5))
    tf._inflight.clear()
    assert (
        tf.schedule(["aa1", "aa2", "aa3", "aa4"]) == 2
    )  # 넘치는 것은 거절(다음 조회 때 다시 맡긴다)
    gate.set()


def test_unsafe_ids_are_never_used_as_file_names(monkeypatch):
    monkeypatch.setattr(tf, "schedule", _REAL_SCHEDULE)
    assert tf.load("../etc") is None and tf.failure("a/b") is None
    assert tf.schedule(["../x", "a b", ""]) == 0


def test_forgetting_removes_the_stored_analysis(client, family):
    a, _, _ = family
    att = _candidate(client, a, BASE_DAY)
    assert tf._sig_path(att).exists()
    tf.forget(att)
    assert not tf._sig_path(att).exists() and tf.load(att) is None


def test_deleting_the_message_removes_the_photo_from_the_timeline_and_its_analysis(client, family):
    a, _, _ = family
    att = _candidate(client, a, BASE_DAY)
    mid = client.get("/family-chat/messages", headers=a).json()
    message_id = next(
        m["id"] for m in (mid["items"] if isinstance(mid, dict) else mid) if m.get("attachment")
    )
    assert client.delete(f"/family-chat/messages/{message_id}", headers=a).status_code == 200
    assert _timeline(client, a)["items"] == []
    assert not tf._sig_path(att).exists()


# ---------- 묶기 순수 함수 ----------
def _gi(att, minutes, emb=None, batch=None, day_offset=0):
    return tg.GroupItem(
        att,
        BASE_DAY + timedelta(days=day_offset, minutes=minutes),
        batch,
        tuple(emb) if emb else None,
    )


def test_grouping_caps_the_group_size_and_never_chains_without_limit():
    base = unit(BASE)
    items = [_gi(f"p{i:03d}", i, similar_to(base, 0.05)) for i in range(tg.MAX_GROUP + 10)]
    result = tg.group_items(items)
    sizes: dict[str | None, int] = {}
    for assign in result.values():
        sizes[assign.key] = sizes.get(assign.key, 0) + 1
    assert max(sizes.values()) <= tg.MAX_GROUP


def test_grouping_without_embeddings_leaves_singles_and_upload_batches_only():
    result = tg.group_items(
        [_gi("a1", 0), _gi("a2", 1), _gi("a3", 2, batch="bbbb1111"), _gi("a4", 3, batch="bbbb1111")]
    )
    assert result["a1"].kind == result["a2"].kind == "single"
    assert result["a3"].kind == result["a4"].kind == "batch" and result["a3"].key == "bbbb1111"


def _angled(degrees: float) -> list[float]:
    """평면의 각도로 만든 단위 벡터(768차원에 0 을 채움). 두 벡터의 코사인 유사도는 각도 차의 cos 값이다."""
    v = np.zeros(768)
    v[0], v[1] = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    return list(v)


def test_grouping_never_chains_a_to_c_through_b_when_a_and_c_are_not_similar():
    # A–B 15°(0.966), B–C 28°(0.883), A–C 43°(0.731 < 0.88): 쌍 하나만 비슷해서 사슬로 합치면 안 된다
    a, b, c = _angled(0), _angled(15), _angled(43)
    result = tg.group_items([_gi("p1", 0, a), _gi("p2", 1, b), _gi("p3", 2, c)])
    assert (
        result["p1"].kind == result["p2"].kind == "similar" and result["p1"].key == result["p2"].key
    )
    assert result["p3"].kind == "single"  # C 는 A 와 비슷하지 않으므로 {A, B} 에 들어가지 못한다


def test_grouping_merges_when_every_pair_is_similar():
    a, b, c = _angled(0), _angled(8), _angled(16)  # 모든 쌍이 0.88 이상(최대 각도 차 16° = 0.961)
    result = tg.group_items([_gi("p1", 0, a), _gi("p2", 1, b), _gi("p3", 2, c)])
    assert {x.kind for x in result.values()} == {"similar"} and len(
        {x.key for x in result.values()}
    ) == 1


def test_upload_batch_photos_are_never_used_for_similar_grouping():
    same = unit(BASE)
    result = tg.group_items(
        [
            _gi("b1", 0, same, batch="batch0001"),
            _gi("b2", 1, same, batch="batch0001"),
            _gi("s1", 2, same),  # 업로드 묶음 사진과 똑같아도 이어 붙이지 않는다
            _gi("s2", 3, same),
        ]
    )
    assert result["b1"].kind == result["b2"].kind == "batch" and result["b1"].key == "batch0001"
    assert result["s1"].kind == result["s2"].kind == "similar" and result["s1"].key != "batch0001"


def test_a_single_photo_upload_with_a_batch_id_can_still_join_similar_photos():
    same = unit(BASE)
    result = tg.group_items([_gi("a1", 0, same, batch="lonely0001"), _gi("a2", 1, same)])
    assert result["a1"].kind == result["a2"].kind == "similar"


def test_grouping_is_deterministic_for_the_same_input():
    items = [_gi(f"q{i}", i * 3, similar_to(BASE)) for i in range(8)]
    assert tg.group_items(items) == tg.group_items(list(reversed(items)))


def test_cosine_threshold_is_between_unrelated_and_near_duplicate_photos():
    near = float(np.dot(unit(BASE), similar_to(BASE, 0.15)))
    far = float(np.dot(unit(BASE), unit(OTHER)))
    assert far < tg.SIM_THRESHOLD <= near


# ---------- 실제 모델(선택): 환경변수로 폴더를 주면 실제 ONNX 로 임베딩 모양을 확인한다 ----------
@pytest.mark.skipif(
    not __import__("os").environ.get("GABEE_SIGLIP_TEST_DIR"),
    reason="실제 SigLIP2 ONNX 폴더(GABEE_SIGLIP_TEST_DIR)가 있을 때만 확인하는 선택 시험",
)
def test_real_onnx_returns_a_normalized_768_embedding_and_the_same_margin_as_score():
    import os

    from app.features.ai_assistant.ingest.siglip_margin import OnnxMarginScorer

    scorer = OnnxMarginScorer(os.environ["GABEE_SIGLIP_TEST_DIR"], threads=2)
    data = _jpeg()
    margin, emb = scorer.analyze(data)
    assert len(emb) == 768 and abs(sum(v * v for v in emb) - 1.0) < 1e-3
    assert abs(margin - scorer.score(data)) < 1e-6
