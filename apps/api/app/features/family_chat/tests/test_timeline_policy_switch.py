"""날짜별 타임라인의 자동 후보·유사 묶기는 서버 스위치(기본 꺼짐)와 ADR 0020 조건을 모두 만족할 때만 동작한다(ADR 0026).

- 스위치 꺼짐(기본): 이미지 분석을 맡기지 않고 임베딩을 쓰지 않으며 자동 후보를 보이지 않는다. 업로더가 확인했거나 직접 넣은 사진만 보인다(D-8 유지).
- 스위치 켜짐 + ADR 0020(FAMILY_MEMORY_ENABLED·가족 활성화·업로더 동의, 사진별 분석 제외 없음)을 실제 family_memory 기록으로 만족해야 분석·노출한다.
- 동의 철회·가족 비활성화·사진 분석 제외 때 그 사진의 타임라인 분석 결과(임베딩)를 지운다.
외부 AI 호출은 막혀 있다(test_timeline_mvp 의 격리 픽스처). 분석 함수는 대역이다."""

from datetime import UTC, datetime

import pytest

from app.features.family_chat import timeline_features as tf
from app.features.family_chat.tests.test_timeline_mvp import (  # noqa: F401  (격리 픽스처·도우미 재사용)
    BASE,
    BASE_DAY,
    TIMELINE,
    _isolated,
    _put,
    _send,
    _status_set,
    _taken,
    _timeline,
    similar_to,
    unit,
)
from app.features.family_memory.models import (
    FamilyMemorySetting,
    MemberMemoryConsent,
    PhotoAnalysisExclusion,
)
from app.shared import memory_hooks, photo_analysis_consent
from app.shared.config import settings
from app.shared.db import SessionLocal

_REAL_CHECKER = photo_analysis_consent._checker  # family_memory 가 등록한 실제 확인 함수
ACK = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}


@pytest.fixture
def switch_off(monkeypatch):
    monkeypatch.setattr(settings, "timeline_auto_candidates", False)  # 기본값 그대로
    monkeypatch.setattr(photo_analysis_consent, "_checker", _REAL_CHECKER)


@pytest.fixture
def real_consent(monkeypatch):
    """스위치는 켜고 동의 확인은 실제 family_memory 기록으로 한다."""
    monkeypatch.setattr(settings, "timeline_auto_candidates", True)
    monkeypatch.setattr(photo_analysis_consent, "_checker", _REAL_CHECKER)


def _uid(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _memory_on(
    group_id: str,
    user_id: str,
    monkeypatch,
    *,
    family=True,
    consent=True,
    consented_at=None,
    retro=False,
) -> None:
    """ADR 0020 조건을 실제 family_memory 기록으로 만든다. 동의 시각 기본값은 사진을 올리기 전(먼 과거)이라 소급 동의가 필요 없다."""
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    with SessionLocal() as db:
        db.merge(FamilyMemorySetting(group_id=group_id, enabled=family))
        db.merge(
            MemberMemoryConsent(
                group_id=group_id,
                user_id=user_id,
                consented_at=(consented_at or datetime(2020, 1, 1, tzinfo=UTC))
                if consent
                else None,
                retro_consented_at=datetime.now(UTC) if retro else None,
            )
        )
        db.commit()


def _candidate(client, headers, emb=None, margin=-3.0) -> str:
    att = _send(client, headers)
    _taken(att, BASE_DAY)
    _put(att, margin, emb if emb is not None else unit(BASE))
    return att


def _shown(client, headers) -> set[str]:
    return {i["attachment_id"] for i in _timeline(client, headers)["items"]}


# ---------- 스위치 꺼짐(기본) ----------
def test_the_switch_is_off_by_default():
    assert type(settings).model_fields["timeline_auto_candidates"].default is False
    assert tf.enabled() in (True, False)


def test_switch_off_hides_auto_candidates_and_schedules_nothing(
    client, family, switch_off, monkeypatch
):
    a, _, _ = family
    calls = []
    monkeypatch.setattr(tf, "schedule", lambda ids: calls.append(list(ids)) or 0)
    att = _candidate(client, a)  # 분석 결과가 있어도(예전 캐시) 자동 후보로 쓰지 않는다
    body = _timeline(client, a)
    assert att not in {i["attachment_id"] for i in body["items"]}
    assert body["analyzing"] == 0 and body["analysis_failed"] == 0
    assert calls == []  # 업로드 직후·조회 때 분석을 맡기지 않는다


def test_switch_off_still_shows_confirmed_and_explicitly_included_photos(
    client, family, switch_off
):
    a, _, _ = family
    confirmed = _send(client, a)
    _taken(confirmed, BASE_DAY)
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck
    from app.features.family_chat.tests.test_timeline_mvp import _status  # noqa: F401

    with SessionLocal() as db:  # 업로더가 일반 사진으로 확인한 상태(15분 대기 없이)
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == confirmed)
            .values(status="photo", source="manual")
        )
        db.commit()
    included = _send(client, a)
    _taken(included, BASE_DAY)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == included)
            .values(status="document", source="auto")
        )
        db.commit()
    r = client.post(f"/family-chat/photos/{included}/timeline-include", json=ACK, headers=a)
    assert r.status_code == 200, r.text
    assert _shown(client, a) == {confirmed, included}


def test_switch_off_never_uses_embeddings_for_grouping(client, family, switch_off):
    """확인된 사진에 예전 분석 결과가 남아 있어도 스위치가 꺼져 있으면 유사 묶기에 쓰지 않는다(같은 업로드 묶음만)."""
    a, _, _ = family
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck

    ids = []
    for _ in range(2):
        att = _send(client, a)
        _taken(att, BASE_DAY)
        _put(att, -3.0, similar_to(BASE))
        ids.append(att)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id.in_(ids))
            .values(status="photo", source="manual")
        )
        db.commit()
    items = _timeline(client, a)["items"]
    assert {i["attachment_id"] for i in items} == set(ids)
    assert all(i["group_kind"] == "single" for i in items)


# ---------- 스위치 켜짐 + ADR 0020 실제 조건 ----------
def test_switch_on_without_family_activation_or_consent_shows_nothing_automatic(
    client, family, real_consent, monkeypatch
):
    a, _, group = family
    att = _candidate(client, a)
    assert att not in _shown(
        client, a
    )  # family_memory 기록이 없다(서버 스위치·가족·동의 모두 없음)
    _memory_on(group["id"], _uid(client, a), monkeypatch, family=False)
    assert att not in _shown(client, a)  # 가족 활성화 없음
    _memory_on(group["id"], _uid(client, a), monkeypatch, family=True, consent=False)
    assert att not in _shown(client, a)  # 업로더 동의 없음


def test_switch_on_with_all_adr_0020_conditions_shows_the_candidate(
    client, family, real_consent, monkeypatch
):
    a, b, group = family
    att = _candidate(client, a)
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    assert att in _shown(client, a)
    assert att in _shown(client, b)  # 같은 가족 구성원에게 보인다


def test_another_uploader_without_consent_is_not_analyzed(
    client, family, real_consent, monkeypatch
):
    a, b, group = family
    mine = _candidate(client, a)
    theirs = _candidate(client, b)
    _memory_on(group["id"], _uid(client, a), monkeypatch)  # a 만 동의
    shown = _shown(client, a)
    assert mine in shown and theirs not in shown


def test_a_photo_excluded_from_ai_analysis_is_not_shown(client, family, real_consent, monkeypatch):
    a, _, group = family
    att = _candidate(client, a)
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    with SessionLocal() as db:
        db.add(
            PhotoAnalysisExclusion(attachment_id=att, group_id=group["id"], user_id=_uid(client, a))
        )
        db.commit()
    assert att not in _shown(client, a)


def test_a_just_uploaded_photo_waits_for_the_judgement_before_any_analysis(
    client, family, real_consent, monkeypatch
):
    """판별 대기(pending) 사진은 동의가 있어도 업로드 때 분석하지 않는다. 판별이 끝나 애매(unsure)가 된 뒤 조회 때 맡긴다(ADR 0026 분석 범위)."""
    a, _, group = family
    calls = []
    monkeypatch.setattr(tf, "schedule", lambda ids: calls.append(list(ids)) or 0)
    _send(client, a, judged=None)
    assert calls == []  # 동의 없음
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    att = _send(client, a, judged=None)
    assert not any(att in c for c in calls)  # 동의가 있어도 판별 대기 중에는 맡기지 않는다
    _timeline(client, a)
    assert not any(att in c for c in calls)  # 조회 때도 대기 줄은 범위 밖
    _status_set(att, "unsure")  # 판별이 끝났다
    _timeline(client, a)
    assert any(att in c for c in calls)


# ---------- 철회·비활성화·분석 제외 때 파생 데이터 삭제 ----------
@pytest.mark.parametrize("event", ["withdrawn", "family_disabled", "photo_excluded"])
def test_withdrawal_family_disable_and_exclusion_delete_the_timeline_analysis(
    client, family, real_consent, event
):
    a, _, group = family
    att = _candidate(client, a)
    assert tf._sig_path(att).exists()
    with SessionLocal() as db:
        if event == "withdrawn":
            memory_hooks.member_withdrawn(db, group["id"], _uid(client, a))
        elif event == "family_disabled":
            memory_hooks.family_disabled(db, group["id"])
        else:
            memory_hooks.photo_excluded(db, group["id"], att)
        db.commit()
    assert not tf._sig_path(att).exists()  # 임베딩·margin 파일이 지워졌다
    assert tf.load(att) is None


def test_timeline_unaffected_for_other_families(
    client, family, other_family, real_consent, monkeypatch
):
    a, _, group = family
    att = _candidate(client, a)
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    other = {i["attachment_id"] for i in client.get(TIMELINE, headers=other_family).json()["items"]}
    assert att not in other


def test_confirmed_or_included_photos_are_analyzed_for_grouping_when_allowed(
    client, family, real_consent, monkeypatch
):
    """직접 확인·포함한 사진은 자동 후보 목록에 없지만, 스위치와 ADR 0020 조건을 만족하면 같은 날 유사 묶기를 위해 분석을 맡긴다(분석 결과가 없을 때만)."""
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck

    a, _, group = family
    att = _send(client, a)
    _taken(att, BASE_DAY)
    with SessionLocal() as db:  # 판별이 끝난 애매한 사진(업로더가 확인할 수 있는 상태)
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == att)
            .values(status="unsure")
        )
        db.commit()
    r = client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a)
    assert r.status_code == 200, r.text
    calls = []
    monkeypatch.setattr(tf, "schedule", lambda ids: calls.append(list(ids)) or 0)
    _timeline(client, a)
    assert calls == []  # 동의 전: 맡기지 않는다
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    _timeline(client, a)
    assert any(att in c for c in calls)  # 동의 뒤: 묶기용 분석을 맡긴다
    calls.clear()
    _put(att, -3.0, unit(BASE))  # 분석 결과가 생기면 다시 맡기지 않는다
    _timeline(client, a)
    assert not any(att in c for c in calls)


# ---------- 독립 리뷰 반영: 소급 동의·진행 중 작업·묶기 게이트·실제 API·쪽 넘기기 ----------
def test_the_real_family_memory_checker_is_registered():
    assert _REAL_CHECKER is not None  # 등록되지 않았으면 위의 부정 시험들이 의미 없이 통과한다


def test_photos_uploaded_before_consent_need_retro_consent(
    client, family, real_consent, monkeypatch
):
    a, _, group = family
    att = _candidate(client, a)  # 동의하기 전에 올린 사진
    _memory_on(group["id"], _uid(client, a), monkeypatch, consented_at=datetime.now(UTC))
    assert att not in _shown(
        client, a
    )  # 소급 동의 없음: 분석·노출하지 않는다(ADR 0020 '과거 사진')
    _memory_on(
        group["id"], _uid(client, a), monkeypatch, consented_at=datetime.now(UTC), retro=True
    )
    assert att in _shown(client, a)


def test_a_running_analysis_does_not_recreate_the_file_after_forget(
    client, family, real_consent, monkeypatch
):
    """작업이 도는 사이 철회·삭제로 forget 되면 결과를 쓰지 않는다(파생 데이터가 되살아나지 않게)."""
    from app.shared import image_features

    a, _, group = family
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    att = _send(client, a)

    def analyzer(data):
        tf.forget(att)  # 분석하는 동안 철회됐다
        return -3.0, unit(BASE)

    image_features.register_analyzer(analyzer)
    assert tf.analyze_attachment(att) is False
    assert not tf._sig_path(att).exists() and tf.failure(att) is None


def test_the_write_guard_rechecks_consent_right_before_writing(
    client, family, real_consent, monkeypatch
):
    from app.shared import image_features

    a, _, group = family
    uid = _uid(client, a)
    _memory_on(group["id"], uid, monkeypatch)
    att = _send(client, a)

    def analyzer(data):
        _memory_on(
            group["id"], uid, monkeypatch, consent=False
        )  # 훅 없이 동의가 사라져도 막혀야 한다
        return -3.0, unit(BASE)

    image_features.register_analyzer(analyzer)
    assert tf.analyze_attachment(att) is False
    assert not tf._sig_path(att).exists()


def test_grouping_uses_only_embeddings_of_consented_uploaders(
    client, family, real_consent, monkeypatch
):
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck

    a, b, group = family
    mine = _candidate(client, a, emb=similar_to(BASE))
    theirs = _candidate(client, b, emb=similar_to(BASE))
    with SessionLocal() as db:  # 둘 다 업로더가 확인한 사진(노출은 동의와 무관)
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id.in_([mine, theirs]))
            .values(status="photo", source="manual")
        )
        db.commit()
    _memory_on(group["id"], _uid(client, a), monkeypatch)  # a 만 동의
    items = {i["attachment_id"]: i for i in _timeline(client, a)["items"]}
    assert {mine, theirs} <= set(items)
    assert items[theirs]["group_kind"] == "single"  # 동의 없는 b 의 임베딩은 묶기에 쓰지 않는다


def test_withdrawing_through_the_real_api_deletes_the_analysis(
    client, family, real_consent, monkeypatch
):
    a, _, _ = family
    monkeypatch.setattr(settings, "family_memory_enabled", True)
    r = client.put("/family-memory/settings", json={"enabled": True}, headers=a)
    assert r.status_code == 200, r.text
    r = client.put("/family-memory/consent", json={"consent": True}, headers=a)
    assert r.status_code == 200, r.text
    att = _candidate(client, a)
    assert att in _shown(client, a)
    r = client.put("/family-memory/consent", json={"consent": False}, headers=a)
    assert r.status_code == 200, r.text
    assert not tf._sig_path(att).exists()
    assert att not in _shown(client, a)


def test_switch_off_pages_through_every_confirmed_photo_beyond_the_window(
    client, family, switch_off, monkeypatch
):
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck

    a, _, _ = family
    monkeypatch.setattr(tf, "WINDOW_CAP", 2)  # 꺼짐 경로는 창 상한과 무관하게 DB 커서로 끝까지 간다
    ids = []
    for i in range(5):
        att = _send(client, a)
        _taken(att, BASE_DAY.replace(day=10 + i))
        ids.append(att)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id.in_(ids))
            .values(status="photo", source="manual")
        )
        db.commit()
    seen, before = [], None
    for _ in range(5):
        body = _timeline(client, a, limit=2, **({"before": before} if before else {}))
        seen += [i["attachment_id"] for i in body["items"]]
        before = body["next_before"]
        if not before:
            break
    assert len(seen) == 5 and sorted(seen) == sorted(ids)


def test_excluding_an_auto_candidate_keeps_the_judgement_row(
    client, family, real_consent, monkeypatch
):
    from app.features.family_chat.models import ChatPhotoCheck

    a, _, group = family
    att = _candidate(client, a)
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    assert att in _shown(client, a)
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        before = (row.status, row.source)
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        after = (row.status, row.source)
    assert after == before == ("unsure", "auto")  # 판별 줄은 그대로(선택은 이력 줄)
    assert att not in _shown(client, a)
    r = client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a)
    assert r.status_code == 200
    assert att in _shown(client, a)


# ---------- 분석 범위(ADR 0026, 2026-11-25 축소): photo·자동 unsure 만, document·pending·failed 제외 ----------
def test_a_failed_judgement_row_is_never_an_automatic_candidate(
    client, family, real_consent, monkeypatch
):
    a, _, group = family
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    att = _send(client, a, judged="failed")
    _taken(att, BASE_DAY)
    _put(att, -3.0, unit(BASE))  # 예전 분석 결과가 남아 있어도
    body = _timeline(client, a)
    assert att not in {i["attachment_id"] for i in body["items"]}
    assert body["analyzing"] == 0 and body["analysis_failed"] == 0


def test_the_write_guard_drops_a_photo_that_became_a_document_while_queued(
    client, family, real_consent, monkeypatch
):
    from app.shared import image_features

    a, _, group = family
    _memory_on(group["id"], _uid(client, a), monkeypatch)
    att = _send(client, a)  # 판별이 끝난 애매(unsure)

    def analyzer(data):
        _status_set(att, "document")  # 분석하는 사이 문서함 판별이 문서로 바뀌었다
        return -3.0, unit(BASE)

    image_features.register_analyzer(analyzer)
    assert tf.analyze_attachment(att) is False
    assert not tf._sig_path(att).exists()
