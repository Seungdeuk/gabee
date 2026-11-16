"""사진 판별 상태 표(T05-b0-1): 업로드와 같은 트랜잭션, 삭제 정리, 자동 판별 결과가 덮어쓰지 못하는 규칙, 수동 문서 저장, 권한 격리, fail-closed.
D-13: 자동 판별은 `photo` 를 만들지 못한다(일반 사진 확인은 업로더가, b0-2)."""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat import photo_service as ps
from app.features.family_chat.models import ChatPhotoCheck, Message, MessageAttachment
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ps.library_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    # 문서함 등록(뒤에서 하는 판별)은 이 시험의 대상이 아니다: 통로를 비운다
    monkeypatch.setattr(chat_library, "_on_photo", None)


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
    return r.json()["attachment"]


def _check(attachment_id: str) -> ChatPhotoCheck | None:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, attachment_id)


def _record(group_id, attachment_id, status, error=None) -> bool:
    with SessionLocal() as db:
        return checks.record_auto(db, group_id, attachment_id, status, error)


def _gid(client, headers) -> str:
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


# ---------- 업로드와 같은 트랜잭션 ----------


def test_family_room_photo_creates_a_pending_row_with_the_group(client, family):
    a, _, _ = family
    att = _send(client, a)
    row = _check(att["id"])
    assert (row.status, row.source, row.group_id) == ("pending", "auto", _gid(client, a))
    assert row.checked_at is None and row.last_error is None


def test_one_to_one_room_photo_creates_no_row(client, family):
    a, b, _ = family
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    att = _send(client, a, room_id=room["id"])
    assert _check(att["id"]) is None


def test_if_the_row_cannot_be_saved_message_attachment_and_row_all_roll_back(
    client, family, monkeypatch, tmp_path
):
    a, _, _ = family

    def boom(attachment_id, group_id):
        raise RuntimeError("row failed")

    monkeypatch.setattr(checks, "new_pending", boom)
    with pytest.raises(RuntimeError):
        client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a)
    with SessionLocal() as db:
        for model in (Message, MessageAttachment, ChatPhotoCheck):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert list((tmp_path / "chat_photos").glob("*")) == []  # 파일도 남지 않는다


def test_if_the_commit_fails_nothing_is_left_and_the_session_is_usable(client, family, monkeypatch):
    a, _, _ = family
    real = checks.new_pending

    def bad_group(attachment_id, group_id):
        row = real(attachment_id, group_id)
        row.group_id = None  # NOT NULL 위반: SQLite 도 커밋에서 실패한다
        return row

    monkeypatch.setattr(checks, "new_pending", bad_group)
    with pytest.raises(Exception):  # noqa: B017  어떤 DB 오류든 업로드 전체가 실패해야 한다
        client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a)
    monkeypatch.setattr(checks, "new_pending", real)
    with SessionLocal() as db:
        for model in (Message, MessageAttachment, ChatPhotoCheck):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert _send(client, a)["id"]  # 다음 업로드는 정상


def test_deleting_the_photo_message_removes_its_row(client, family):
    a, _, _ = family
    sent = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    assert _check(sent["attachment"]["id"]) is not None
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
    assert _check(sent["attachment"]["id"]) is None


def test_photo_upload_does_not_touch_other_attachments_rows(client, family):
    a, _, _ = family
    first, second = _send(client, a), _send(client, a)
    assert {_check(first["id"]).status, _check(second["id"]).status} == {"pending"}
    assert first["id"] != second["id"]


# ---------- 자동 판별 결과 기록 ----------


@pytest.mark.parametrize("status", ["document", "unsure", "failed"])
def test_auto_result_sets_a_pending_row_once(client, family, status):
    a, _, _ = family
    att, gid = _send(client, a), _gid(client, a)
    assert _record(gid, att["id"], status, "OcrFailed" if status == "failed" else None) is True
    row = _check(att["id"])
    assert (row.status, row.source) == (status, "auto") and row.checked_at is not None
    assert row.last_error == ("OcrFailed" if status == "failed" else None)


def test_auto_can_never_confirm_a_general_photo(client, family):
    """D-13: OCR·실험 모델의 판정이 무엇이든 자동으로 status='photo' 가 되지 않는다."""
    a, _, _ = family
    att, gid = _send(client, a), _gid(client, a)
    for bad in ("photo", "pending", "PHOTO", "", "whatever"):
        with pytest.raises(ValueError):
            _record(gid, att["id"], bad)
    assert _check(att["id"]).status == "pending"


def test_duplicate_or_late_results_do_not_overwrite(client, family):
    a, _, _ = family
    att, gid = _send(client, a), _gid(client, a)
    assert _record(gid, att["id"], "unsure") is True
    assert _record(gid, att["id"], "unsure") is False  # 중복
    assert _record(gid, att["id"], "failed", "LateError") is False  # 늦게 온 다른 결과
    row = _check(att["id"])
    assert (row.status, row.last_error) == ("unsure", None)


def test_a_later_document_verdict_hides_an_unsure_or_failed_photo(client, family):
    a, _, _ = family
    gid = _gid(client, a)
    for first in ("unsure", "failed"):
        att = _send(client, a)
        _record(gid, att["id"], first)
        assert _record(gid, att["id"], "document") is True
        assert _check(att["id"]).status == "document"
        assert _record(gid, att["id"], "unsure") is False  # 문서는 자동으로 되돌리지 않는다
        assert _check(att["id"]).status == "document"


def test_auto_never_overwrites_a_manual_decision_or_a_confirmed_photo(client, family):
    a, _, _ = family
    gid = _gid(client, a)
    manual, confirmed = _send(client, a), _send(client, a)
    with SessionLocal() as db:
        checks.mark_document_manual(db, gid, manual["id"])
        row = db.get(ChatPhotoCheck, confirmed["id"])
        row.status, row.source = "photo", "manual"  # b0-2 의 업로더 확인이 만들 모습
        db.commit()
    for status in ("document", "unsure", "failed"):
        assert _record(gid, manual["id"], status) is False
        assert _record(gid, confirmed["id"], status) is False
    assert (_check(manual["id"]).status, _check(manual["id"]).source) == ("document", "manual")
    assert (_check(confirmed["id"]).status, _check(confirmed["id"]).source) == ("photo", "manual")


def test_auto_does_not_touch_a_manual_row_even_when_it_is_not_decided_yet(client, family):
    """source 가 manual 인 줄은 status 가 pending·unsure·failed 여도 자동 결과(문서 포함)가 바꾸지 못한다."""
    a, _, _ = family
    gid = _gid(client, a)
    for state in ("pending", "unsure", "failed"):
        att = _send(client, a)
        with SessionLocal() as db:
            row = db.get(ChatPhotoCheck, att["id"])
            row.status, row.source = state, "manual"
            db.commit()
        for result in ("document", "unsure", "failed"):
            assert _record(gid, att["id"], result) is False
        row = _check(att["id"])
        assert (row.status, row.source) == (state, "manual")


def test_auto_result_for_another_group_or_missing_row_changes_nothing(client, family, other_family):
    a, _, _ = family
    att = _send(client, a)
    other_gid = _gid(client, other_family)
    assert other_gid != _gid(client, a)
    assert _record(other_gid, att["id"], "document") is False  # 다른 가족 id 로는 못 바꾼다
    assert _record(_gid(client, a), "nosuchattach", "document") is False
    assert _check(att["id"]).status == "pending"
    with SessionLocal() as db:
        assert db.get(ChatPhotoCheck, "nosuchattach") is None  # 줄을 새로 만들지도 않는다


def test_error_text_is_truncated_and_recorder_failure_never_raises(client, family, monkeypatch):
    a, _, _ = family
    att, gid = _send(client, a), _gid(client, a)
    _record(gid, att["id"], "failed", "E" * 200)
    assert len(_check(att["id"]).last_error) == 40

    def boom(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_library, "_check_recorder", boom)
    chat_library.photo_judged(gid, att["id"], "document")  # 던지지 않는다


# ---------- 수동 "문서로 저장" (D-15: 가족 누구나) ----------


def test_manual_document_save_sets_status_and_blocks_auto(client, family, monkeypatch):
    a, b, _ = family
    att, gid = _send(client, a), _gid(client, a)
    calls = []
    monkeypatch.setattr(chat_library, "photo_requested", lambda *args: calls.append(args))
    r = client.post(f"{PHOTOS}/{att['id']}/library", headers=b)  # 올린 사람이 아닌 가족도 가능
    assert r.status_code == 200, r.text
    row = _check(att["id"])
    assert (row.status, row.source) == ("document", "manual")
    assert _record(gid, att["id"], "unsure") is False and len(calls) == 1


def test_manual_document_save_creates_a_row_for_a_legacy_photo_and_is_idempotent(client, family):
    a, _, _ = family
    att, gid = _send(client, a), _gid(client, a)
    with SessionLocal() as db:
        db.delete(db.get(ChatPhotoCheck, att["id"]))  # 예전 사진: 줄이 없다
        db.commit()
    with SessionLocal() as db:
        checks.mark_document_manual(db, gid, att["id"])
        checks.mark_document_manual(db, gid, att["id"])
    with SessionLocal() as db:
        rows = db.scalars(select(ChatPhotoCheck)).all()
        assert [(r.status, r.source) for r in rows] == [("document", "manual")]


def test_manual_save_by_a_member_of_another_family_cannot_reach_the_photo(
    client, family, other_family
):
    a, _, _ = family
    att = _send(client, a)
    r = client.post(f"{PHOTOS}/{att['id']}/library", headers=other_family)
    assert r.status_code == 404
    assert _check(att["id"]).status == "pending"


def test_manual_save_in_a_one_to_one_room_is_refused_and_leaves_no_row(client, family):
    a, b, _ = family
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    att = _send(client, a, room_id=room["id"])
    assert client.post(f"{PHOTOS}/{att['id']}/library", headers=a).status_code == 409
    assert _check(att["id"]) is None


def test_manual_save_is_refused_when_the_status_cannot_be_written(client, family, monkeypatch):
    """상태를 못 적으면 문서함 요청도 하지 않는다(요청은 실패한다)."""
    a, _, _ = family
    att = _send(client, a)
    calls = []
    monkeypatch.setattr(chat_library, "photo_requested", lambda *args: calls.append(args))

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(checks, "mark_document_manual", boom)
    with pytest.raises(RuntimeError):
        client.post(f"{PHOTOS}/{att['id']}/library", headers=a)
    assert calls == []


def test_manual_save_for_a_photo_deleted_meanwhile_creates_no_orphan_row(client, family):
    a, _, _ = family
    sent = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    att, gid = sent["attachment"]["id"], _gid(client, a)
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
    with SessionLocal() as db:
        checks.mark_document_manual(db, gid, att)  # 삭제 뒤에 늦게 도착한 수동 저장
    assert _check(att) is None


@pytest.fixture
def enforce_foreign_keys():
    """SQLite 는 기본으로 외래 키를 검사하지 않아 삭제 순서 오류를 숨긴다. 이 시험 동안만 검사를 켠다(PostgreSQL 과 같게)."""
    from sqlalchemy import event

    from app.shared.db import engine

    def on_connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", on_connect)
    engine.dispose()
    yield
    event.remove(engine, "connect", on_connect)
    engine.dispose()


def test_family_purge_and_room_purge_remove_the_rows_with_foreign_keys_on(
    client, family, enforce_foreign_keys
):
    from app.shared import group_purge

    a, b, _ = family
    gid = _gid(client, a)
    family_att = _send(client, a)
    other = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": other}, headers=a).json()
    direct_att = _send(client, a, room_id=room["id"])
    assert _check(family_att["id"]) is not None and _check(direct_att["id"]) is None
    with SessionLocal() as db:
        group_purge.purge_room(db, room["id"])  # 1:1 방 정리: 가족 전체방 사진의 줄은 그대로
        db.commit()
    assert _check(family_att["id"]) is not None
    with SessionLocal() as db:
        group_purge.purge_group(
            db, gid
        )  # 가족 삭제: 외래 키 검사가 켜진 채로 위반 없이 줄도 사라진다
        db.commit()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPhotoCheck)) == 0
        assert db.scalar(select(func.count()).select_from(MessageAttachment)) == 0


# ---------- 타임라인용 조회: fail-closed ----------


def test_only_confirmed_photos_in_this_group_are_listed(client, family, other_family):
    a, _, _ = family
    gid = _gid(client, a)
    ids = {}
    for status in ("pending", "photo", "document", "unsure", "failed"):
        att = _send(client, a)
        ids[status] = att["id"]
        if status != "pending":
            with SessionLocal() as db:
                row = db.get(ChatPhotoCheck, att["id"])
                row.status = status
                db.commit()
    nonrow = _send(client, a)
    with SessionLocal() as db:
        db.delete(db.get(ChatPhotoCheck, nonrow["id"]))  # 상태가 없는 사진
        db.commit()
    with SessionLocal() as db:
        wanted = [*ids.values(), nonrow["id"]]
        assert checks.confirmed_photo_ids(db, gid, wanted) == {ids["photo"]}
        assert (
            checks.confirmed_photo_ids(db, "othergroup", wanted) == set()
        )  # 다른 가족 id 로는 안 보인다
        assert checks.confirmed_photo_ids(db, gid, []) == set()


def test_a_read_error_is_not_swallowed():
    """조회가 실패하면 빈 목록이 아니라 오류가 올라온다(타임라인은 이때 503 으로 답해야 한다)."""

    class Broken:
        def scalars(self, *args, **kwargs):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        checks.confirmed_photo_ids(Broken(), "g", ["x"])
