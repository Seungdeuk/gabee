"""사진 판별 재검사(PR2): 실패 원인 표시, 횟수 제한, 멱등, 권한·격리, 삭제·철회·탈퇴 뒤 안전, D-13(자동 photo 금지) 유지."""

import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select, update

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat import photo_service as ps
from app.features.family_chat.models import ChatPhotoCheck, ChatPhotoCheckEvent
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
CONFIRM = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}
_UPLOAD_CALLS: list[tuple] = []  # 판별 통로(`chat_library._on_photo`)가 받은 호출


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ps.library_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    _UPLOAD_CALLS.clear()
    monkeypatch.setattr(chat_library, "_on_photo", lambda *args: _UPLOAD_CALLS.append(args))
    from app.features.family_chat import photo_check_service as pcs

    pcs.check_limiter._failures.clear()


@pytest.fixture
def calls():
    return _UPLOAD_CALLS


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


def _send(client, headers, room_id=None) -> dict:
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    _UPLOAD_CALLS.clear()  # 업로드 자체가 부르는 판별 통로 호출은 세지 않는다(재검사가 부른 것만 센다)
    return r.json()


def _gid(client, headers) -> str:
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _row(attachment_id: str) -> ChatPhotoCheck:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, attachment_id)


def _fail(client, headers, att_id, error="OcrFailed") -> None:
    with SessionLocal() as db:
        assert checks.record_auto(db, _gid(client, headers), att_id, "failed", error)


def _age(att_id, created_minutes=0, checked_minutes=None) -> None:
    now = datetime.now(UTC)
    values = {"created_at": now - timedelta(minutes=created_minutes)}
    if checked_minutes is not None:
        values["checked_at"] = now - timedelta(minutes=checked_minutes)
    with SessionLocal() as db:
        db.execute(
            update(ChatPhotoCheck).where(ChatPhotoCheck.attachment_id == att_id).values(**values)
        )
        db.commit()


def _recheck(client, headers, att_id):
    return client.post(f"{PHOTOS}/{att_id}/recheck", headers=headers)


def _events(att_id) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count())
            .select_from(ChatPhotoCheckEvent)
            .where(
                ChatPhotoCheckEvent.attachment_id == att_id,
                ChatPhotoCheckEvent.reason == checks.REASON_RECHECK,
            )
        )


# ---------- 실패 원인 표시 ----------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        ("OcrFailed", "ocr_failed"),
        ("APITimeoutError", "timeout"),
        ("ReadTimeout", "timeout"),
        ("TimeoutError", "timeout"),
        ("ValueError", "ai_failed"),
        (None, "ai_failed"),
    ],
)
def test_failed_photo_lists_a_structured_failure_kind(client, family, error, kind):
    a, _, _ = family
    att = _send(client, a)["attachment"]
    _fail(client, a, att["id"], error)
    item = client.get(f"{PHOTOS}/checks/mine", headers=a).json()["items"][0]
    assert (item["status"], item["failure_kind"]) == ("failed", kind)
    assert (item["can_retry"], item["retries_left"]) == (True, checks.RECHECK_MAX)
    assert "error" not in item and "last_error" not in item  # 예외 이름 원문은 내보내지 않는다


def test_stale_pending_is_listed_as_stalled_and_retryable_but_unsure_is_not(client, family):
    a, _, _ = family
    stuck = _send(client, a)["attachment"]["id"]
    ambiguous = _send(client, a)["attachment"]["id"]
    _age(stuck, created_minutes=30)
    with SessionLocal() as db:
        checks.record_auto(db, _gid(client, a), ambiguous, "unsure")
    items = {
        i["attachment_id"]: i
        for i in client.get(f"{PHOTOS}/checks/mine", headers=a).json()["items"]
    }
    assert (items[stuck]["failure_kind"], items[stuck]["can_retry"]) == ("stalled", True)
    assert (items[ambiguous]["failure_kind"], items[ambiguous]["can_retry"]) == (None, False)


# ---------- 재검사 ----------


def test_recheck_of_a_failed_photo_requeues_judging_once_and_records_the_request(
    client, family, calls
):
    a, _, _ = family
    sent = _send(client, a)
    att = sent["attachment"]["id"]
    _fail(client, a, att)
    r = _recheck(client, a, att)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "pending", "queued": True, "retries_left": checks.RECHECK_MAX - 1}
    row = _row(att)
    assert (row.status, row.source, row.last_error) == ("pending", "auto", None)
    assert len(calls) == 1 and calls[0][:3] == (_gid(client, a), sent["user_id"], att)
    assert calls[0][4] is False  # 판별을 건너뛰는 강제 저장이 아니다
    assert _events(att) == 1


def test_a_repeated_recheck_does_not_judge_twice(client, family, calls):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    _fail(client, a, att)
    assert _recheck(client, a, att).json()["queued"] is True
    again = _recheck(client, a, att)
    assert again.status_code == 200 and again.json()["queued"] is False
    assert len(calls) == 1 and _events(att) == 1  # 판별도, 횟수도 한 번만


def test_concurrent_rechecks_claim_a_failed_photo_exactly_once(client, family, calls):
    """겹친 요청 여럿이 동시에 와도 맡는 쪽은 하나뿐이고 횟수·이력도 한 번만 늘어난다(조건부 UPDATE)."""
    import threading

    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    _fail(client, a, att)
    gid = _gid(client, a)
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        with SessionLocal() as db:
            barrier.wait()
            outcomes.append(checks.claim_recheck(db, gid, att, "someone"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("claimed") == 1 and set(outcomes) <= {"claimed", "in_progress"}
    assert _events(att) == 1 and _row(att).status == "pending"


def test_recheck_never_exceeds_the_limit_even_when_requested_repeatedly(client, family, calls):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    gid = _gid(client, a)
    claimed = 0
    for _ in range(checks.RECHECK_MAX * 3):
        with SessionLocal() as db:  # 판별이 매번 실패로 끝난다고 보고 줄을 failed 로 맞춘다
            db.execute(
                update(ChatPhotoCheck)
                .where(ChatPhotoCheck.attachment_id == att)
                .values(status="failed", last_error="OcrFailed")
            )
            db.commit()
        with SessionLocal() as db:
            claimed += checks.claim_recheck(db, gid, att, "someone") == "claimed"
    assert claimed == checks.RECHECK_MAX and _events(att) == checks.RECHECK_MAX


def test_recheck_of_a_fresh_pending_photo_is_not_started(client, family, calls):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]  # 방금 올림: 아직 처리 중일 수 있다
    r = _recheck(client, a, att)
    assert r.status_code == 200 and r.json()["queued"] is False
    assert calls == [] and _events(att) == 0


def test_a_stale_pending_photo_can_be_rechecked_then_waits_for_the_cooldown(client, family, calls):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    _age(att, created_minutes=30)
    assert _recheck(client, a, att).json()["queued"] is True
    assert _recheck(client, a, att).json()["queued"] is False  # 방금 맡김
    _age(att, created_minutes=30, checked_minutes=5)  # 맡긴 뒤 처리되지 않고 5분이 지났다
    assert _recheck(client, a, att).json()["queued"] is True
    assert len(calls) == 2 and _events(att) == 2


def test_recheck_count_is_limited_and_the_manual_paths_still_work(client, family, calls):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    for _ in range(checks.RECHECK_MAX):
        _fail(client, a, att)
        assert _recheck(client, a, att).json()["queued"] is True
    _fail(client, a, att)
    over = _recheck(client, a, att)
    assert over.status_code == 409 and over.json()["code"] == "recheck_limit_reached"
    assert _row(att).status == "failed" and len(calls) == checks.RECHECK_MAX
    item = client.get(f"{PHOTOS}/checks/mine", headers=a).json()["items"][0]
    assert (item["can_retry"], item["retries_left"]) == (False, 0)
    # 횟수를 다 써도 업로더는 직접 확인할 수 있다(기존 경로)
    ok = client.post(f"{PHOTOS}/{att}/check", json=CONFIRM, headers=a)
    assert ok.status_code == 200 and _row(att).status == "photo"


@pytest.mark.parametrize("status", ["unsure", "document"])
def test_recheck_is_refused_when_the_photo_is_not_failed_or_stalled(client, family, calls, status):
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    with SessionLocal() as db:
        checks.record_auto(db, _gid(client, a), att, status)
    r = _recheck(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "recheck_not_needed"
    assert calls == [] and _row(att).status == status


def test_recheck_never_touches_confirmed_excluded_or_manual_rows(client, family, calls):
    a, _, _ = family
    confirmed = _send(client, a)["attachment"]["id"]
    with SessionLocal() as db:
        checks.record_auto(
            db, _gid(client, a), confirmed, "unsure"
        )  # 방금 올린 pending 은 확인할 수 없다
    assert client.post(f"{PHOTOS}/{confirmed}/check", json=CONFIRM, headers=a).status_code == 200
    assert _recheck(client, a, confirmed).status_code == 409
    assert client.post(f"{PHOTOS}/{confirmed}/exclude", headers=a).status_code == 200
    assert _recheck(client, a, confirmed).status_code == 409
    manual_doc = _send(client, a)["attachment"]["id"]
    with SessionLocal() as db:
        checks.mark_document_manual(db, _gid(client, a), manual_doc, None)
    assert _recheck(client, a, manual_doc).status_code == 409
    assert calls == []
    assert _row(confirmed).status == "excluded" and _row(manual_doc).source == "manual"


def test_the_result_of_a_recheck_can_never_become_photo(client, family):
    """D-13: 재검사 결과를 적는 길(record_auto)은 photo 를 거부하고, 맡은 줄은 pending 이다(타임라인·분석 자격 없음)."""
    a, _, _ = family
    att = _send(client, a)["attachment"]["id"]
    _fail(client, a, att)
    assert _recheck(client, a, att).json()["queued"] is True
    with SessionLocal() as db, pytest.raises(ValueError):
        checks.record_auto(db, _gid(client, a), att, "photo")
    assert _row(att).status == "pending"
    assert client.get("/family-chat/timeline/photos", headers=a).json()["items"] == []


# ---------- 권한·격리 ----------


def test_only_the_uploader_in_the_family_room_can_recheck(client, family, other_family, calls):
    a, b, _ = family
    att = _send(client, a)["attachment"]["id"]
    _fail(client, a, att)
    assert _recheck(client, b, att).status_code == 404  # 같은 가족의 다른 사람
    assert _recheck(client, other_family, att).status_code == 404  # 다른 가족
    assert _recheck(client, a, "nosuchattach").status_code == 404
    assert calls == [] and _row(att).status == "failed" and _events(att) == 0


def test_a_one_to_one_room_photo_cannot_be_rechecked(client, family, calls):
    a, b, _ = family
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    att = _send(client, a, room_id=room["id"])["attachment"]["id"]
    assert _recheck(client, a, att).status_code == 404
    assert calls == []


# ---------- 삭제·철회·탈퇴 뒤 ----------


def test_a_deleted_photo_cannot_be_rechecked_and_leaves_no_row(client, family, calls):
    a, _, _ = family
    sent = _send(client, a)
    att = sent["attachment"]["id"]
    _fail(client, a, att)
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
    assert _recheck(client, a, att).status_code == 404
    assert calls == [] and _row(att) is None and _events(att) == 0


def test_a_photo_deleted_while_judging_is_not_registered_to_the_library(
    client, family, monkeypatch
):
    """재검사처럼 오래 걸리는 판별 중에 메시지가 지워지면 판별 결과가 와도 문서함에 올리지 않는다."""
    from app.features.ai_assistant import library

    a, _, _ = family
    sent = _send(client, a)
    att, gid = sent["attachment"]["id"], _gid(client, a)
    registered: list[str] = []

    def judge_then_delete(group_id, data):
        assert (
            client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
        )  # 판별하는 사이 삭제
        return "document", None

    monkeypatch.setattr(library, "_judge_photo", judge_then_delete)
    monkeypatch.setattr(
        library.service, "receive_file", lambda *args, **kw: registered.append("x") or None
    )
    library.register_chat_photo(gid, sent["user_id"], att, _jpeg())
    assert registered == []  # 문서함에 올리지 않았다


def test_consent_withdrawal_leave_and_delete_keep_memory_analysis_closed(
    client, family, monkeypatch, calls
):
    """재검사는 기존 사진·문서 판별일 뿐 AI 추억 분석이 아니다. 판별 결과와 상관없이 분석 자격은 PR1 규칙(동의·철회·확인된 사진)을 그대로 따른다."""
    from app.features.family_memory import service as memory

    monkeypatch.setattr(settings, "family_memory_enabled", True)
    a, _, _ = family
    sent = _send(client, a)
    att = sent["attachment"]["id"]
    _fail(client, a, att)
    assert _recheck(client, a, att).json()["queued"] is True
    with SessionLocal() as db:
        # 동의했어도 업로더가 일반 사진으로 확인하기 전(pending·failed·unsure)에는 자격이 없다
        client.put("/family-memory/settings", json={"enabled": True}, headers=a)
        client.put("/family-memory/consent", json={"consent": True}, headers=a)
        assert memory.check_photo(db, att).reason == "not_confirmed_photo"
        checks.record_auto(
            db, _gid(client, a), att, "unsure"
        )  # 재검사 결과: 애매(자동으로 photo 가 되지 않는다)
        assert memory.check_photo(db, att).reason == "not_confirmed_photo"
    assert client.post(f"{PHOTOS}/{att}/check", json=CONFIRM, headers=a).status_code == 200
    with SessionLocal() as db:
        assert memory.check_photo(db, att).reason == "ok"
    client.put("/family-memory/consent", json={"consent": False}, headers=a)  # 철회: 즉시 닫힌다
    with SessionLocal() as db:
        assert memory.check_photo(db, att).reason == "no_consent"
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200  # 삭제
    with SessionLocal() as db:
        gone = memory.check_photo(db, att)
        assert (
            gone.eligible is False
        )  # 지운 사진은 자격이 없다(사유 코드는 PR1 의 fail-closed 순서를 따른다)
