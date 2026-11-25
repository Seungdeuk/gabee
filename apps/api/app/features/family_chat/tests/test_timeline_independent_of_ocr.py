"""가족 타임라인은 기존 OCR·문서함 판정(`chat_photo_checks`)에 갇히지 않는다(2026-11-26 결함 수정).

배경: 업로드 직후 OCR 이 일상 사진을 `document`(자동)로 적으면 타임라인에서 사라지고, 업로더가 `/check` 로 되돌릴 수도 없었다(document→photo 차단).
규칙(타임라인 전용, 2026-11-25 분석 범위 축소 — ADR 0026): 문서(`document`) 줄은 자동 분석·자동 후보가 아니다(예전 OCR 이 적은 자동 줄도).
업로더가 직접 넣으면(timeline-include) 보이고, 업로더의 명시적 제외·포함은 **문서함 판정 줄(`chat_photo_checks`)을 바꾸지 않는다**(선택은 이력 줄로만 영속).
자동 후보는 판별이 끝난 애매(unsure) 줄만이고 SigLIP2 margin ≤ 5·분석 성공일 때만 보인다.
사람이 문서로 저장한(manual) 줄은 자동 후보가 아니다. 외부 AI 호출은 대역이 막는다(autouse `_isolated`: 부르면 시험 실패).
분석 함수는 대역이라 정확도를 평가하지 않는다: 규칙이 설계대로 동작하는지만 본다."""

from sqlalchemy import select

from app.features.family_chat import timeline_features as tf
from app.features.family_chat.models import ChatPhotoCheck, ChatPhotoCheckEvent
from app.features.family_chat.tests.test_timeline_mvp import (  # noqa: F401  (autouse 격리 픽스처·도우미 재사용)
    BASE,
    BASE_DAY,
    TIMELINE,
    _isolated,
    _put,
    _send,
    _taken,
    _timeline,
    unit,
)
from app.shared import chat_library
from app.shared.db import SessionLocal

SCENE = unit(BASE)
DOC_MARGIN = 12.0  # 영수증 같은 문서 사진의 margin(대역 값)


def _ocr_says_document(att: str, source: str = "auto") -> None:
    """기존 OCR 경로가 이 사진을 문서로 적은 상태를 만든다(문서함 등록 경로의 결과 줄 그대로)."""
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = "document", source
        db.commit()


def _row(att: str) -> tuple:
    with SessionLocal() as db:
        r = db.get(ChatPhotoCheck, att)
        return (r.status, r.source, r.last_error, r.checked_at)


def _events(att: str) -> list[tuple]:
    with SessionLocal() as db:
        return list(
            db.execute(
                select(
                    ChatPhotoCheckEvent.from_status,
                    ChatPhotoCheckEvent.to_status,
                    ChatPhotoCheckEvent.reason,
                ).where(ChatPhotoCheckEvent.attachment_id == att)
            ).all()
        )


def _shown(client, headers) -> dict[str, dict]:
    return {i["attachment_id"]: i for i in _timeline(client, headers)["items"]}


def _restart() -> None:
    """서버 재시작: 메모리(캐시·진행 중 목록)는 사라지고 DB·디스크 파일만 남는다."""
    tf._cache.clear()
    tf._inflight.clear()


ACK = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}


def _scene_ocr_document(client, headers, margin=-3.0, source="auto") -> str:
    att = _send(client, headers)
    _taken(att, BASE_DAY)
    _put(att, margin, SCENE)
    _ocr_says_document(att, source)
    return att


# 1·2·3 문서 줄은 margin 이 낮아도 자동 후보가 아니다 → 업로더가 직접 넣으면 보인다(문서함 판정 줄은 그대로)
def test_an_auto_document_row_is_not_an_automatic_candidate_even_with_a_low_margin(
    client, family, monkeypatch
):
    a, _, _ = family
    scheduled = []
    monkeypatch.setattr(tf, "schedule", lambda ids: scheduled.append(list(ids)) or 0)
    att = _scene_ocr_document(
        client, a
    )  # 예전 OCR 이 문서로 적은 장면 사진(분석 결과는 일반 사진 쪽)
    before = _row(att)
    assert att not in _shown(client, a)  # 문서 줄은 자동 분석·자동 노출 범위 밖
    assert not any(att in ids for ids in scheduled)  # 분석을 맡기지도 않는다
    assert _row(att) == before and before[:2] == ("document", "auto")  # 문서함 판정은 읽기만 했다
    assert _events(att) == []
    r = client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a)
    assert r.status_code == 200, r.text
    items = _shown(client, a)
    assert att in items and items[att]["confirmed"] is True  # 업로더의 명시적 포함으로만 보인다
    assert _row(att) == before


# 9 실제 문서 이미지의 자동 포함 방지
def test_a_real_document_image_is_not_automatically_included_even_if_ocr_agrees(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a, margin=DOC_MARGIN)
    assert att not in _shown(client, a)
    _restart()
    assert att not in _shown(client, a)


def test_document_pending_and_failed_rows_are_neither_analyzed_nor_counted(client, family):
    """분석 범위 밖(문서·판별 대기·판별 실패) 줄은 분석 전·실패 수에도 세지 않는다(정리 중으로 보이지 않는다)."""
    a, _, _ = family
    doc = _send(client, a)
    _taken(doc, BASE_DAY)
    _ocr_says_document(doc)
    pending = _send(client, a, judged=None)  # 문서함 판별이 아직 끝나지 않았다
    _taken(pending, BASE_DAY)
    failed = _send(client, a, judged="failed")  # 문서함 판별 실패
    _taken(failed, BASE_DAY)
    tf._write_atomic(tf._fail_path(doc), '{"kind": "ModelDirMissing", "at": 9e12}')
    body = _timeline(client, a)
    assert body["items"] == []
    assert body["analyzing"] == 0 and body["analysis_failed"] == 0


def test_a_document_the_family_saved_by_hand_is_never_an_automatic_candidate(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a, source="manual")  # 사람이 문서함에 저장한 사진
    assert att not in _shown(client, a)


# 4·5 업로더가 제외 → 다시 나타나지 않는다(재시작·재분석 뒤에도) / 8 문서함 판정 불변
def test_the_uploader_excludes_it_and_it_never_comes_back(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a)
    before = _row(att)
    # 문서 줄은 자동으로 보이지 않으므로 뺄 것이 없다(409). 업로더가 넣은 뒤에만 뺄 수 있다
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 409
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    assert att not in _shown(client, a)
    assert _row(att) == before  # 문서함 판정 줄(status/source/last_error/checked_at)이 그대로다
    assert _events(att) == [
        ("document", "tl_include", "timeline_include"),
        ("document", "tl_exclude", "timeline_exclude"),
    ]
    # 같은 요청 반복: 200, 이력은 늘지 않는다
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    assert len(_events(att)) == 2
    # 재분석(모델이 같은 결과를 다시 냄)·재시작 뒤에도 안 나온다
    _put(att, -9.0, SCENE)
    assert tf.analyze_attachment(att) in (True, False)
    _restart()
    assert att not in _shown(client, a)
    # 다시 넣을 사진을 찾을 수 있게 "뺀 사진" 목록에 보인다(상태는 excluded 로 표기)
    r = client.get("/family-chat/photos/checks/mine", params={"kind": "excluded"}, headers=a).json()
    assert [(i["attachment_id"], i["status"]) for i in r["items"]] == [(att, "excluded")]


# 6·7 업로더가 수동으로 다시 포함 → 재시작 뒤에도 유지, `/check` 의 document→photo 차단은 그대로
def test_the_uploader_includes_it_again_and_the_choice_survives_restart(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a)
    before = _row(att)
    client.post(f"/family-chat/photos/{att}/exclude", headers=a)
    assert att not in _shown(client, a)
    # 문서함의 document→photo 변경 제한은 그대로다
    blocked = client.post(f"/family-chat/photos/{att}/check", json=ACK, headers=a)
    assert blocked.status_code == 409 and blocked.json()["code"] == "document_to_photo_blocked"
    r = client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a)
    assert r.status_code == 200, r.text
    items = _shown(client, a)
    assert att in items and items[att]["confirmed"] is True
    assert _row(att) == before  # 문서함 판정은 끝까지 그대로
    _restart()
    assert att in _shown(client, a)
    # 뺀 사진 목록에서는 빠진다
    r = client.get("/family-chat/photos/checks/mine", params={"kind": "excluded"}, headers=a).json()
    assert r["items"] == []
    # 같은 요청 반복은 200, 이력은 늘지 않는다
    n = len(_events(att))
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert len(_events(att)) == n
    # 다시 빼면 다시 사라진다(마지막 선택이 이긴다)
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    assert att not in _shown(client, a)


def test_an_explicit_include_beats_the_model_even_for_a_document_looking_photo(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a, margin=DOC_MARGIN)  # 모델도 문서라고 본다
    assert att not in _shown(client, a)
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert att in _shown(client, a)  # 업로더가 직접 넣으면 모델의 자동 판정보다 우선한다


def test_an_explicit_exclude_beats_a_candidate_model_result(client, family):
    a, _, _ = family
    att = _send(client, a)  # 판별이 끝난 애매(unsure) 줄의 일반 후보
    _taken(att, BASE_DAY)
    _put(att, -3.0, SCENE)
    assert att in _shown(client, a)
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    _put(att, -3.0, SCENE)
    assert att not in _shown(client, a)


def test_excluding_and_reincluding_an_auto_candidate_never_touches_the_judgement_row(
    client, family
):
    """자동 판별 줄(대기·애매·실패)의 제외·다시 넣기는 타임라인 선택(이력 줄)으로만 남는다. 줄을 excluded 로 덮으면
    뒤늦게 끝난 판별·문서함 등록과 어긋난다(독립 리뷰 지적). 판정 줄은 자동 판별이 계속 갱신한다."""
    a, _, _ = family
    att = _send(client, a)
    _taken(att, BASE_DAY)
    _put(att, -3.0, SCENE)
    assert client.post(f"/family-chat/photos/{att}/exclude", headers=a).status_code == 200
    assert _row(att)[:2] == ("unsure", "auto")
    assert att not in _shown(client, a)
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert _row(att)[:2] == ("unsure", "auto")
    assert att in _shown(client, a)


def test_an_unsure_photo_without_a_choice_is_still_confirmed_as_a_general_photo(client, family):
    """선택 기록이 없는 애매한 줄을 직접 넣으면 기존 일반 사진 확인(D-13 업로더 확인)과 같다."""
    from sqlalchemy import update

    from app.features.family_chat.models import ChatPhotoCheck
    from app.shared.db import SessionLocal

    a, _, _ = family
    att = _send(client, a)
    _taken(att, BASE_DAY)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck)
            .where(ChatPhotoCheck.attachment_id == att)
            .values(status="unsure")
        )
        db.commit()
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert _row(att)[:2] == ("photo", "manual")
    assert att in _shown(client, a)


def test_a_photo_registered_in_the_library_can_be_included_without_touching_the_library(
    client, family, monkeypatch
):
    a, _, _ = family
    att = _send(client, a)
    _taken(att, BASE_DAY)
    _put(att, -3.0, SCENE)
    client.post(f"/family-chat/photos/{att}/exclude", headers=a)
    monkeypatch.setattr(
        chat_library, "_is_registered", lambda db, g, x: True
    )  # 문서함에 등록된 사진
    before = _row(att)
    assert client.post(f"/family-chat/photos/{att}/check", json=ACK, headers=a).status_code == 409
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert _row(att) == before  # 줄을 바꾸지 않는다
    assert att in _shown(client, a)


def test_an_unverifiable_library_state_never_changes_the_row(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    _taken(att, BASE_DAY)
    _put(att, -3.0, SCENE)
    client.post(f"/family-chat/photos/{att}/exclude", headers=a)
    monkeypatch.setattr(chat_library, "_is_registered", None)  # 확인 수단 없음 → None
    before = _row(att)
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert _row(att) == before
    assert att in _shown(client, a)


def test_excluding_a_photo_that_is_not_in_the_timeline_is_a_conflict(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a, margin=DOC_MARGIN)  # 문서로 보여 타임라인에 없다
    r = client.post(f"/family-chat/photos/{att}/exclude", headers=a)
    assert r.status_code == 409 and r.json()["code"] == "not_in_timeline"
    assert _events(att) == []


# 가족방 격리·업로더만
def test_only_the_uploader_in_the_same_family_can_change_the_timeline_choice(
    client, family, other_family
):
    a, b, _ = family
    att = _scene_ocr_document(client, a)
    for who in (b, other_family):  # 같은 가족의 다른 구성원, 다른 가족
        assert client.post(f"/family-chat/photos/{att}/exclude", headers=who).status_code == 404
        r = client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=who)
        assert r.status_code == 404
    assert _events(att) == []
    assert (
        client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a).status_code
        == 200
    )
    assert att in _shown(client, a) and att in _shown(
        client, b
    )  # 업로더가 넣으면 같은 가족에게는 보인다
    assert att not in {
        i["attachment_id"] for i in client.get(TIMELINE, headers=other_family).json()["items"]
    }
    # 수동 선택도 다른 가족에게는 새지 않는다
    client.post(f"/family-chat/photos/{att}/exclude", headers=a)
    client.post(f"/family-chat/photos/{att}/timeline-include", json=ACK, headers=a)
    assert att not in {
        i["attachment_id"] for i in client.get(TIMELINE, headers=other_family).json()["items"]
    }


def test_the_include_endpoint_requires_the_notice_acknowledgement(client, family):
    a, _, _ = family
    att = _scene_ocr_document(client, a)
    r = client.post(
        f"/family-chat/photos/{att}/timeline-include", json={**ACK, "acknowledge": False}, headers=a
    )
    assert r.status_code == 422


def test_group_and_room_purge_also_remove_the_derived_analysis_files(client, family):
    """가족·방을 지울 때 사진 파일뿐 아니라 분석 결과(임베딩 JSON)·실패 기록도 디스크에서 지운다(개인정보 파생물이 남지 않게)."""
    from app.shared import group_purge

    a, _, group = family
    att = _scene_ocr_document(client, a)
    with SessionLocal() as db:
        paths = group_purge._attachment_paths(db, lambda t: t.c.group_id == group["id"])
    names = {p.name for p in paths}
    assert {f"{att}.jpg", f"{att}_t.jpg", f"{att}_sig.json", f"{att}_sigfail.json"} <= names
