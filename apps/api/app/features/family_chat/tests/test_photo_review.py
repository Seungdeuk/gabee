"""업로더 확인 필요 목록·일반 사진 확인·변경 이력·문서함 조회(T05-b0-2a).
규칙: 일반 사진(`photo`) 확정은 업로더 본인이 명시적으로 확인했을 때만(D-13), document→photo 는 MVP 에서 차단(D-15·D-16),
이력은 상태가 실제로 바뀔 때만 한 줄(D-19), 자동 판별은 사람의 확인을 덮어쓰지 못한다(b0-1), 조회 오류는 빈 목록이 아니라 503."""

import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat import photo_check_service as pcs
from app.features.family_chat import photo_service as ps
from app.features.family_chat.models import (
    ChatPhotoCheck,
    ChatPhotoCheckEvent,
    Message,
    MessageAttachment,
)
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import allow_ai

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
BODY = {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": True}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ps.library_limiter._failures.clear()
    pcs.check_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(chat_library, "_on_photo", None)
    monkeypatch.setattr(chat_library, "_is_registered", lambda db, g, a: False)


@pytest.fixture
def family(client, family, monkeypatch):
    """사진 속 글자는 Claude 로만 읽으므로(로컬 OCR 없음) 사진을 문서함에 저장·등록하려면 가족 AI 동의가 있어야 한다: 이 모듈의 가족은 동의한 상태로 둔다."""
    allow_ai(client, family[0], monkeypatch)
    return family


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(out, format="JPEG")
    return out.getvalue()


def _send(client, headers, room_id=None) -> str:
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["attachment"]["id"]


def _gid(client, headers) -> str:
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _uid(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _row(att) -> ChatPhotoCheck | None:
    with SessionLocal() as db:
        return db.get(ChatPhotoCheck, att)


def _events(att) -> list[ChatPhotoCheckEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(ChatPhotoCheckEvent)
                .where(ChatPhotoCheckEvent.attachment_id == att)
                .order_by(ChatPhotoCheckEvent.id)
            )
        )


def _set(att, status, source="auto", age_minutes=0):
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = status, source
        row.created_at = datetime.now(UTC) - timedelta(minutes=age_minutes)
        db.commit()


def _confirm(client, headers, att, body=BODY):
    return client.post(f"{PHOTOS}/{att}/check", json=body, headers=headers)


def _mine(client, headers, **params):
    return client.get(f"{PHOTOS}/checks/mine", params=params, headers=headers)


# ---------- 확인 필요 목록 ----------


def test_list_shows_only_my_unsure_failed_and_stale_pending_photos(client, family):
    a, b, _ = family
    unsure, failed, stale, fresh, doc, photo = (_send(client, a) for _ in range(6))
    theirs = _send(client, b)
    _set(unsure, "unsure")
    _set(failed, "failed")
    _set(stale, "pending", age_minutes=16)
    _set(doc, "document")
    _set(photo, "photo", "manual")
    _set(theirs, "unsure")
    out = _mine(client, a).json()
    assert {i["attachment_id"]: i["status"] for i in out["items"]} == {
        unsure: "unsure",
        failed: "failed",
        stale: "pending",
    }
    assert out["needs_review_count"] == 3 and out["next_before"] is None
    assert fresh not in {i["attachment_id"] for i in out["items"]}
    # 다른 가족 구성원의 목록에는 내 사진이 하나도 없다(존재를 새로 알리지 않는다)
    assert [i["attachment_id"] for i in _mine(client, b).json()["items"]] == [theirs]


def test_pending_boundary_is_fifteen_minutes(client, family):
    a, _, _ = family
    young, old = _send(client, a), _send(client, a)
    _set(young, "pending", age_minutes=14)
    _set(old, "pending", age_minutes=16)
    ids = {i["attachment_id"] for i in _mine(client, a).json()["items"]}
    assert ids == {old}


def test_list_item_shape_and_thumb_url(client, family):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    item = _mine(client, a).json()["items"][0]
    assert item["thumb_url"] == f"/family-chat/photos/{att}?size=thumb"
    # 기존 필드는 그대로이고, PR2 가 원인 코드·재검사 가능 여부·남은 횟수만 더했다(예외 이름·사진 내용·글자는 내보내지 않는다)
    assert set(item) == {
        "attachment_id",
        "thumb_url",
        "created_at",
        "taken_at",
        "status",
        "failure_kind",
        "can_retry",
        "retries_left",
    }
    # unsure 는 재검사 대상이 아니다
    assert (item["failure_kind"], item["can_retry"]) == (None, False)


def test_list_excludes_one_to_one_deleted_and_other_group_photos(client, family, other_family):
    a, b, _ = family
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    family_att = _send(client, a)
    gone = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    with (
        SessionLocal() as db
    ):  # 1:1 방 사진에 (있어서는 안 되는) 판별 줄이 있어도 목록에는 나오지 않는다(방 종류를 목록 쪽에서도 거른다)
        db.add(
            ChatPhotoCheck(
                attachment_id=direct, group_id=_gid(client, a), status="unsure", source="auto"
            )
        )
        db.commit()
    _set(family_att, "unsure")
    _set(gone["attachment"]["id"], "unsure")
    client.delete(f"{MSG}/{gone['id']}", headers=a)
    assert [i["attachment_id"] for i in _mine(client, a).json()["items"]] == [family_att]
    assert _mine(client, other_family).json() == {
        "items": [],
        "needs_review_count": 0,
        "next_before": None,
    }


def test_list_paginates_newest_first(client, family):
    a, _, _ = family
    ids = [_send(client, a) for _ in range(3)]
    for att in ids:
        _set(att, "unsure")
    first = _mine(client, a, limit=2).json()
    assert [i["attachment_id"] for i in first["items"]] == [ids[2], ids[1]]
    assert first["needs_review_count"] == 3 and first["next_before"] is not None
    second = _mine(client, a, limit=2, before=first["next_before"]).json()
    assert [i["attachment_id"] for i in second["items"]] == [ids[0]]
    assert second["next_before"] is None


def test_list_requires_login_and_group(client, family):
    assert client.get(f"{PHOTOS}/checks/mine").status_code in (401, 403)


def test_list_database_error_is_503_not_an_empty_list(client, family, monkeypatch):
    from sqlalchemy.exc import OperationalError

    a, _, _ = family

    def boom(*args, **kwargs):
        raise OperationalError("select", {}, Exception("db down"))

    monkeypatch.setattr(checks, "list_review", boom)
    r = _mine(client, a)
    assert r.status_code == 503 and r.json()["code"] == "photo_checks_unavailable"


# ---------- 일반 사진 확인 ----------


@pytest.mark.parametrize("status", ["unsure", "failed"])
def test_uploader_confirms_unsure_or_failed_photo_with_one_history_line(client, family, status):
    a, _, _ = family
    att = _send(client, a)
    _set(att, status)
    r = _confirm(client, a, att)
    assert r.status_code == 200 and r.json() == {"status": "photo", "source": "manual"}
    row = _row(att)
    assert (row.status, row.source) == ("photo", "manual")
    [event] = _events(att)
    assert (event.from_status, event.to_status, event.reason) == (
        status,
        "photo",
        "uploader_confirmed_general",
    )
    assert event.actor_user_id == _uid(client, a) and event.group_id == _gid(client, a)
    assert att not in {i["attachment_id"] for i in _mine(client, a).json()["items"]}


def test_stale_pending_can_be_confirmed_and_a_late_auto_result_cannot_override(client, family):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "pending", age_minutes=20)
    assert _confirm(client, a, att).status_code == 200
    with SessionLocal() as db:  # 늦게 도착한 자동 결과(b0-1 수동 보호)
        for late in ("document", "unsure", "failed"):
            assert checks.record_auto(db, _gid(client, a), att, late) is False
    assert (_row(att).status, _row(att).source) == ("photo", "manual")


def test_fresh_pending_is_in_progress_and_nothing_changes(client, family):
    a, _, _ = family
    att = _send(client, a)
    r = _confirm(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "check_in_progress"
    assert _row(att).status == "pending" and _events(att) == []


def test_pending_fifteen_minute_boundary_for_confirm(client, family):
    a, _, _ = family
    att = _send(client, a)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        created = db.get(ChatPhotoCheck, att).created_at.replace(tzinfo=UTC)
        assert (
            checks.confirm_general(
                db,
                _gid(client, a),
                att,
                _uid(client, a),
                now=created + timedelta(minutes=14, seconds=59),
            )
            == "in_progress"
        )
        assert (
            checks.confirm_general(
                db, _gid(client, a), att, _uid(client, a), now=created + timedelta(minutes=15)
            )
            == "confirmed"
        )
    assert now  # 시계는 주입한다: 실제 시각에 기대지 않는다


@pytest.mark.parametrize("source", ["auto", "manual"])
def test_document_to_photo_is_blocked_for_auto_and_manual_documents(client, family, source):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "document", source)
    r = _confirm(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "document_to_photo_blocked"
    assert (_row(att).status, _row(att).source) == ("document", source) and _events(att) == []


def test_registered_in_library_is_blocked_even_if_the_row_says_unsure(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    monkeypatch.setattr(chat_library, "_is_registered", lambda db, g, i: True)
    r = _confirm(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "document_to_photo_blocked"
    assert _row(att).status == "unsure" and _events(att) == []


def test_library_lookup_failure_blocks_confirmation_fail_closed(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")

    def boom(db, g, i):
        raise RuntimeError("library down")

    monkeypatch.setattr(chat_library, "_is_registered", boom)
    r = _confirm(client, a, att)
    assert r.status_code == 503 and _row(att).status == "unsure" and _events(att) == []
    monkeypatch.setattr(chat_library, "_is_registered", None)  # 확인 함수가 아예 없어도 막는다
    assert _confirm(client, a, att).status_code == 503 and _row(att).status == "unsure"


def test_repeated_confirmation_is_ok_and_leaves_one_history_line(client, family):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    assert _confirm(client, a, att).status_code == 200
    assert _confirm(client, a, att).status_code == 200
    assert len(_events(att)) == 1


def test_only_the_uploader_may_confirm_others_get_404(client, family, other_family):
    a, b, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    for headers in (b, other_family):
        r = _confirm(client, headers, att)
        assert r.status_code == 404
    assert _row(att).status == "unsure" and _events(att) == []
    # 존재 여부를 숨긴다: 아예 없는 사진과 같은 응답
    assert _confirm(client, b, "nope00000000").json() == _confirm(client, b, att).json()
    assert _confirm(client, b, att).status_code == _confirm(client, b, "nope00000000").status_code


def test_one_to_one_deleted_and_legacy_photos_are_not_confirmable(client, family):
    a, b, _ = family
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    assert _confirm(client, a, direct).status_code == 404
    legacy = _send(client, a)
    with SessionLocal() as db:  # b0-1 이전 사진: 판별 줄이 없다
        db.delete(db.get(ChatPhotoCheck, legacy))
        db.commit()
    assert _confirm(client, a, legacy).status_code == 404 and _row(legacy) is None
    gone = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    client.delete(f"{MSG}/{gone['id']}", headers=a)
    assert _confirm(client, a, gone["attachment"]["id"]).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"to": "photo", "reason": "uploader_confirmed_general"},
        {"to": "photo", "reason": "uploader_confirmed_general", "acknowledge": False},
        {"to": "document", "reason": "uploader_confirmed_general", "acknowledge": True},
        {"to": "photo", "reason": "anything else", "acknowledge": True},
        {},
    ],
)
def test_missing_acknowledge_or_wrong_values_are_422_and_change_nothing(client, family, body):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    assert _confirm(client, a, att, body).status_code == 422
    assert _row(att).status == "unsure" and _events(att) == []


def test_confirmation_requests_are_rate_limited(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    monkeypatch.setattr(pcs, "CHECK_LIMIT", 2)
    assert _confirm(client, a, att).status_code == 200
    assert _confirm(client, a, att).status_code == 200
    r = _confirm(client, a, att)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_confirm_database_error_is_503_and_session_stays_usable(client, family, monkeypatch):
    from sqlalchemy.exc import OperationalError

    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    real = checks.confirm_general

    def boom(*args, **kwargs):
        raise OperationalError("update", {}, Exception("db down"))

    monkeypatch.setattr(checks, "confirm_general", boom)
    assert _confirm(client, a, att).status_code == 503
    monkeypatch.setattr(checks, "confirm_general", real)
    assert _confirm(client, a, att).status_code == 200


def test_history_is_rolled_back_with_the_state_if_it_cannot_be_written(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")

    def boom(*args, **kwargs):
        raise RuntimeError("event failed")

    monkeypatch.setattr(checks, "_add_event", boom)
    with pytest.raises(RuntimeError):
        _confirm(client, a, att)
    assert (
        _row(att).status == "unsure" and _events(att) == []
    )  # 상태만 바뀌고 이력이 없는 일은 없다


# ---------- 동시성(같은 세션 안에서 읽기와 쓰기 사이에 끼어든 변경) ----------


def test_confirmation_loses_to_a_document_result_that_lands_between_read_and_update(client, family):
    a, _, _ = family
    att = _send(client, a)
    gid, uid = _gid(client, a), _uid(client, a)
    _set(att, "unsure")
    with SessionLocal() as db:
        real_execute = db.execute
        state = {"raced": False}

        def racing_execute(stmt, *args, **kwargs):
            # `SELECT ... FOR UPDATE` 에도 "UPDATE" 가 들어 있어 문자열만 보면 읽기 전에 끼어든다: 실제 UPDATE 문(표 이름)만 본다
            if not state["raced"] and "UPDATE CHAT_PHOTO_CHECKS" in str(stmt).upper():
                state["raced"] = True
                with SessionLocal() as other:  # 읽은 뒤·쓰기 전에 자동 판별이 문서로 바꾼다
                    assert checks.record_auto(other, gid, att, "document") is True
            return real_execute(stmt, *args, **kwargs)

        db.execute = racing_execute
        assert checks.confirm_general(db, gid, att, uid) == "document"
    assert _row(att).status == "document" and _events(att) == []


def test_two_confirmations_in_a_row_write_one_history_line_even_with_stale_reads(client, family):
    a, _, _ = family
    att = _send(client, a)
    gid, uid = _gid(client, a), _uid(client, a)
    _set(att, "failed")
    with SessionLocal() as one, SessionLocal() as two:
        assert checks.confirm_general(one, gid, att, uid) == "confirmed"
        assert checks.confirm_general(two, gid, att, uid) == "already"
    assert len(_events(att)) == 1


# ---------- 문서로 저장(가족 누구나) 이력 ----------


@pytest.mark.parametrize("prior", ["pending", "unsure", "failed", "photo", "document"])
def test_family_save_as_document_records_history_only_when_the_state_changes(client, family, prior):
    a, b, _ = family
    att = _send(client, a)
    _set(att, prior, "manual" if prior == "photo" else "auto")
    assert client.post(f"{PHOTOS}/{att}/library", headers=b).status_code == 200
    assert (
        client.post(f"{PHOTOS}/{att}/library", headers=b).status_code == 200
    )  # 두 번째는 이력 없음
    assert (_row(att).status, _row(att).source) == ("document", "manual")
    [event] = _events(att)
    assert (event.from_status, event.to_status, event.reason) == (
        prior,
        "document",
        "family_saved_as_document",
    )
    assert event.actor_user_id == _uid(client, b)


def test_legacy_photo_without_a_row_gets_a_row_and_history_with_null_from_status(client, family):
    a, b, _ = family
    att = _send(client, a)
    with SessionLocal() as db:
        db.delete(db.get(ChatPhotoCheck, att))
        db.commit()
    assert client.post(f"{PHOTOS}/{att}/library", headers=b).status_code == 200
    [event] = _events(att)
    assert event.from_status is None and event.to_status == "document"


def test_after_a_manual_document_the_uploader_cannot_turn_it_back_into_a_photo(client, family):
    a, b, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    client.post(f"{PHOTOS}/{att}/library", headers=b)  # 가족이 문서로 저장
    r = _confirm(client, a, att)
    assert r.status_code == 409 and _row(att).status == "document"
    assert [e.to_status for e in _events(att)] == ["document"]


# ---------- 이력의 수명과 사용자 삭제(D-19) ----------


def test_history_is_removed_with_the_message(client, family):
    a, _, _ = family
    sent = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    att = sent["attachment"]["id"]
    _set(att, "unsure")
    _confirm(client, a, att)
    assert len(_events(att)) == 1
    client.delete(f"{MSG}/{sent['id']}", headers=a)
    assert _events(att) == [] and _row(att) is None


@pytest.fixture
def enforce_foreign_keys():
    """SQLite 는 기본으로 외래 키를 검사하지 않는다. 이 시험 동안만 켠다(PostgreSQL 과 같게)."""
    from sqlalchemy import event

    from app.shared.db import engine

    def on_connect(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    event.listen(engine, "connect", on_connect)
    engine.dispose()
    yield
    event.remove(engine, "connect", on_connect)
    engine.dispose()


def test_deleting_the_user_row_keeps_the_history_and_nulls_only_the_actor(
    client, family, enforce_foreign_keys
):
    """D-19: nullable FK + ON DELETE SET NULL. 사용자 행을 지워도 전후 상태·이유·시각은 남는다(SQLite 에서 FK 를 켠 상태)."""
    from sqlalchemy import delete, text

    from app.features.family_group.models import User
    from tests.helpers import signup

    a, b, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    client.post(f"{PHOTOS}/{att}/library", headers=b)  # 이력 한 줄(actor = b)
    # 지금은 다른 표의 외래 키(멤버십·메시지 등) 때문에 실제 사용자 행 삭제가 막혀 있다(D-7, 담당자 확인 전).
    # 그래서 다른 표에 얽히지 않은 사용자를 행위자로 바꿔 놓고 "사용자 행이 지워지는 경우"의 FK 동작만 본다.
    lone = signup(client, "탈퇴자")
    actor = _uid(client, lone)
    with SessionLocal() as db:
        db.execute(
            ChatPhotoCheckEvent.__table__.update()
            .where(ChatPhotoCheckEvent.attachment_id == att)
            .values(actor_user_id=actor)
        )
        db.commit()
    with SessionLocal() as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        db.execute(delete(User).where(User.id == actor))
        db.commit()
    [event] = _events(att)
    assert event.actor_user_id is None
    assert (event.from_status, event.to_status, event.reason) == (
        "unsure",
        "document",
        "family_saved_as_document",
    )
    assert event.created_at is not None


def test_anonymising_the_actor_leaves_no_user_identifier_in_the_history(client, family):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    _confirm(client, a, att)
    columns = {c.name for c in ChatPhotoCheckEvent.__table__.columns}
    assert columns == {
        "id",
        "attachment_id",
        "group_id",
        "actor_user_id",
        "from_status",
        "to_status",
        "reason",
        "created_at",
    }  # 이름·이메일·문자열 식별자 칸이 없다: 사용자 행의 익명화만으로 "누가"가 끊긴다
    fk = next(iter(ChatPhotoCheckEvent.__table__.c.actor_user_id.foreign_keys))
    assert fk.ondelete == "SET NULL" and ChatPhotoCheckEvent.__table__.c.actor_user_id.nullable


def test_family_and_message_purge_remove_the_history_with_foreign_keys_on(
    client, family, enforce_foreign_keys
):
    from app.shared import group_purge

    a, b, _ = family
    gid = _gid(client, a)
    att = _send(client, a)
    _set(att, "unsure")
    _confirm(client, a, att)
    other = _send(client, a)
    _set(other, "unsure")
    client.post(f"{PHOTOS}/{other}/library", headers=b)
    assert _events(att) and _events(other)
    with SessionLocal() as db:
        group_purge.purge_group(db, gid)
        db.commit()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPhotoCheckEvent)) == 0
        assert db.scalar(select(func.count()).select_from(MessageAttachment)) == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


# ---------- 문서함 등록 여부 조회 ----------


def test_library_state_registered_and_not_registered_for_any_family_member(
    client, family, monkeypatch
):
    a, b, _ = family
    att = _send(client, a)
    assert client.get(f"{PHOTOS}/{att}/library", headers=b).json() == {"state": "not_registered"}
    monkeypatch.setattr(chat_library, "_is_registered", lambda db, g, i: True)
    assert client.get(f"{PHOTOS}/{att}/library", headers=b).json() == {"state": "registered"}


def test_library_state_unknown_is_never_reported_as_registered(client, family, monkeypatch):
    a, _, _ = family
    att = _send(client, a)

    def boom(db, g, i):
        raise RuntimeError("down")

    monkeypatch.setattr(chat_library, "_is_registered", boom)
    assert client.get(f"{PHOTOS}/{att}/library", headers=a).json() == {"state": "not_registered"}


def test_library_state_isolation_and_one_to_one(client, family, other_family):
    a, b, _ = family
    att = _send(client, a)
    assert client.get(f"{PHOTOS}/{att}/library", headers=other_family).status_code == 404
    assert client.get(f"{PHOTOS}/nope00000000/library", headers=a).status_code == 404
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    assert client.get(f"{PHOTOS}/{direct}/library", headers=a).status_code == 409


def test_save_as_document_again_retries_registration_idempotently(client, family, monkeypatch):
    a, b, _ = family
    att = _send(client, a)
    calls = []
    monkeypatch.setattr(chat_library, "_on_photo", lambda g, u, i, d, forced: calls.append(forced))
    assert client.post(f"{PHOTOS}/{att}/library", headers=b).json() == {"status": "queued"}
    assert client.get(f"{PHOTOS}/{att}/library", headers=b).json() == {"state": "not_registered"}
    assert client.post(f"{PHOTOS}/{att}/library", headers=b).json() == {
        "status": "queued"
    }  # 재시도
    assert (
        calls == [True, True] and _row(att).status == "document"
    )  # 상태는 계속 document: 타임라인에 나오지 않는다
    monkeypatch.setattr(chat_library, "_is_registered", lambda db, g, i: True)
    assert client.post(f"{PHOTOS}/{att}/library", headers=b).json() == {"status": "already"}
    assert len(_events(att)) == 1


def test_failed_registration_never_makes_the_photo_confirmed(client, family):
    a, b, _ = family
    att = _send(client, a)
    client.post(f"{PHOTOS}/{att}/library", headers=b)  # 등록은 시작만 했고 끝나지 않았다
    with SessionLocal() as db:
        assert checks.confirmed_photo_ids(db, _gid(client, a), [att]) == set()


def test_confirm_does_not_call_ai_or_leave_unrelated_rows(client, family):
    a, _, _ = family
    att = _send(client, a)
    _set(att, "unsure")
    _confirm(client, a, att)  # AI 호출은 _isolated 의 boom 이 막는다
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPhotoCheckEvent)) == 1
