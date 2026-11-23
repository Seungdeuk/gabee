"""가족 타임라인 조회와 "타임라인에서 빼기/다시 넣기"(T05-b).
규칙: 타임라인에는 일반 사진(`photo`)으로 확인된 가족 전체방 사진만 나오고(fail-closed), 빼기·다시 넣기는 업로더 본인만 한다.
뺀 사진은 `excluded`(수동)가 되어 확인 필요 목록에 다시 뜨지 않고, 자동 판별은 이를 바꾸지 못하며, 이력은 실제로 바뀔 때만 한 줄."""

import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_chat import photo_check_repository as checks
from app.features.family_chat import photo_check_service as pcs
from app.features.family_chat import photo_service as ps
from app.features.family_chat.models import (
    ChatPhotoCheck,
    ChatPhotoCheckEvent,
    MessageAttachment,
)
from app.shared import chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
TIMELINE = "/family-chat/timeline/photos"
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


def _uid(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _set(att, status, source="auto"):
    with SessionLocal() as db:
        row = db.get(ChatPhotoCheck, att)
        row.status, row.source = status, source
        db.commit()


def _shown(client, headers) -> str:
    """일반 사진으로 확인된 사진 한 장을 올린다."""
    att = _send(client, headers)
    _set(att, "photo", "manual")
    return att


def _attach(att, **fields):
    with SessionLocal() as db:
        row = db.get(MessageAttachment, att)
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


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


def _timeline(client, headers, **params):
    return client.get(TIMELINE, params=params, headers=headers)


def _ids(client, headers, **params) -> list[str]:
    r = _timeline(client, headers, **params)
    assert r.status_code == 200, r.text
    return [i["attachment_id"] for i in r.json()["items"]]


def _exclude(client, headers, att):
    return client.post(f"{PHOTOS}/{att}/exclude", headers=headers)


def _confirm(client, headers, att):
    return client.post(f"{PHOTOS}/{att}/check", json=BODY, headers=headers)


def _mine(client, headers, **params):
    return client.get(f"{PHOTOS}/checks/mine", params=params, headers=headers)


# ---------- 타임라인 조회: 무엇이 나오는가 ----------


def test_timeline_shows_only_confirmed_photos(client, family):
    a, b, _ = family
    shown = _shown(client, a)
    theirs = _shown(client, b)
    for status in ("pending", "unsure", "failed", "document", "excluded"):
        _set(_send(client, a), status)
    assert set(_ids(client, a)) == {shown, theirs}
    assert set(_ids(client, b)) == {shown, theirs}  # 가족 누구나 같은 타임라인을 본다


def test_timeline_excludes_deleted_direct_and_other_group_photos(client, family, other_family):
    a, b, _ = family
    kept = _shown(client, a)
    gone = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    _set(gone["attachment"]["id"], "photo", "manual")
    client.delete(f"{MSG}/{gone['id']}", headers=a)
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    with SessionLocal() as db:  # 1:1 방 사진에 (있어서는 안 되는) photo 줄이 있어도 나오지 않는다
        db.add(
            ChatPhotoCheck(
                attachment_id=direct,
                group_id=db.get(MessageAttachment, direct).group_id,
                status="photo",
                source="manual",
            )
        )
        db.commit()
    theirs = _shown(client, other_family)
    assert _ids(client, a) == [kept]
    assert _ids(client, other_family) == [theirs]  # 다른 가족 사진은 섞이지 않는다


def test_timeline_item_shape_and_mine_flag(client, family):
    a, b, _ = family
    att = _shown(client, a)
    item = _timeline(client, a).json()["items"][0]
    assert set(item) == {
        "attachment_id",
        "message_id",
        "thumb_url",
        "display_at",
        "taken_at",
        "created_at",
        "batch_id",
        "mine",
    }
    assert item["thumb_url"] == f"/family-chat/photos/{att}?size=thumb"
    assert item["mine"] is True and item["taken_at"] is None and item["batch_id"] is None
    assert _timeline(client, b).json()["items"][0]["mine"] is False


def test_timeline_requires_login(client, family):
    assert client.get(TIMELINE).status_code in (401, 403)


def test_timeline_database_error_is_503_not_an_empty_list(client, family, monkeypatch):
    from sqlalchemy.exc import OperationalError

    a, _, _ = family

    def boom(*args, **kwargs):
        raise OperationalError("select", {}, Exception("db down"))

    monkeypatch.setattr(checks, "list_timeline", boom)
    r = _timeline(client, a)
    assert r.status_code == 503 and r.json()["code"] == "photo_checks_unavailable"


# ---------- 정렬·묶음·쪽 넘기기 ----------


def test_timeline_orders_by_taken_at_then_falls_back_to_sent_time(client, family):
    a, _, _ = family
    old_taken, new_taken, no_taken = (_shown(client, a) for _ in range(3))
    now = datetime.now(UTC)
    _attach(old_taken, taken_at=now - timedelta(days=400), created_at=now)
    _attach(new_taken, taken_at=now - timedelta(days=2), created_at=now - timedelta(days=1))
    _attach(no_taken, taken_at=None, created_at=now - timedelta(days=10))
    # 가장 최근 촬영일 → 촬영일 없는(보낸 날 기준) → 오래된 촬영일. 보낸 순서(old 가 가장 늦게 보냄)와 무관하다.
    assert _ids(client, a) == [new_taken, no_taken, old_taken]
    items = {i["attachment_id"]: i for i in _timeline(client, a).json()["items"]}
    assert items[no_taken]["taken_at"] is None


def test_timeline_batch_uses_earliest_date_for_the_whole_batch(client, family):
    a, _, _ = family
    first, second, other = (_shown(client, a) for _ in range(3))
    now = datetime.now(UTC)
    _attach(first, batch_id="batch-aaaaaaaa", taken_at=now - timedelta(days=30), created_at=now)
    _attach(second, batch_id="batch-aaaaaaaa", taken_at=now - timedelta(days=1), created_at=now)
    _attach(other, taken_at=now - timedelta(days=10), created_at=now)
    items = _timeline(client, a).json()["items"]
    by_id = {i["attachment_id"]: i for i in items}
    assert (
        by_id[first]["display_at"] == by_id[second]["display_at"]
    )  # 묶음 대표는 가장 이른 날짜(Q4)
    assert [i["attachment_id"] for i in items][0] == other  # 묶음 전체가 30일 전으로 내려간다
    assert by_id[second]["batch_id"] == "batch-aaaaaaaa"


def test_timeline_batch_ignores_hidden_members_when_picking_the_date(client, family):
    a, _, _ = family
    shown = _shown(client, a)
    hidden = _send(client, a)
    _set(hidden, "unsure")  # 숨은 사진의 촬영일이 보이는 사진 날짜를 끌어내리면 안 된다
    now = datetime.now(UTC)
    _attach(shown, batch_id="batch-bbbbbbbb", taken_at=now - timedelta(days=1), created_at=now)
    _attach(hidden, batch_id="batch-bbbbbbbb", taken_at=now - timedelta(days=90), created_at=now)
    item = _timeline(client, a).json()["items"][0]
    assert item["attachment_id"] == shown
    assert datetime.fromisoformat(item["display_at"]).date() == (now - timedelta(days=1)).date()


def test_timeline_paginates_with_cursor_without_gaps_or_repeats(client, family):
    a, _, _ = family
    ids = [_shown(client, a) for _ in range(5)]
    now = datetime.now(UTC)
    for n, att in enumerate(ids):  # 같은 날짜 두 장(동점)도 섞는다
        _attach(att, taken_at=now - timedelta(days=n // 2), created_at=now)
    seen: list[str] = []
    before = None
    for _ in range(5):
        out = _timeline(client, a, limit=2, **({"before": before} if before else {})).json()
        seen += [i["attachment_id"] for i in out["items"]]
        before = out["next_before"]
        if before is None:
            break
    assert before is None
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen)) == 5
    assert seen == _ids(client, a)  # 쪽을 넘겨 받은 순서와 한 번에 받은 순서가 같다


@pytest.mark.parametrize("bad", ["x", "2026-11-16_", "nope_5", "2026-13-40T00:00:00+00:00_1"])
def test_timeline_invalid_cursor_is_422(client, family, bad):
    a, _, _ = family
    r = _timeline(client, a, before=bad)
    assert r.status_code == 422 and r.json()["code"] == "invalid_cursor"


# ---------- 빼기 ----------


def test_uploader_removes_photo_from_timeline_with_one_history_line(client, family):
    a, b, _ = family
    att = _shown(client, a)
    r = _exclude(client, a, att)
    assert r.status_code == 200 and r.json() == {"status": "excluded", "source": "manual"}
    row = _row(att)
    assert (row.status, row.source) == ("excluded", "manual")
    assert att not in _ids(client, a) and att not in _ids(client, b)
    events = _events(att)
    assert [(e.from_status, e.to_status, e.reason) for e in events] == [
        ("photo", "excluded", "uploader_removed")
    ]
    assert events[0].actor_user_id == _uid(client, a)


def test_remove_twice_is_ok_and_writes_no_second_history_line(client, family):
    a, _, _ = family
    att = _shown(client, a)
    assert _exclude(client, a, att).status_code == 200
    assert _exclude(client, a, att).status_code == 200
    assert len(_events(att)) == 1


def test_only_the_uploader_can_remove_and_others_get_404(client, family, other_family):
    a, b, _ = family
    att = _shown(client, a)
    for headers in (b, other_family):
        r = _exclude(client, headers, att)
        assert r.status_code == 404
    assert _row(att).status == "photo" and _events(att) == []


@pytest.mark.parametrize("status", ["pending", "unsure", "failed", "document"])
def test_cannot_remove_a_photo_that_is_not_in_the_timeline(client, family, status):
    a, _, _ = family
    att = _send(client, a)
    _set(att, status)
    r = _exclude(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "not_in_timeline"
    assert _row(att).status == status and _events(att) == []


def test_remove_unknown_direct_and_deleted_photos_are_404(client, family):
    a, b, _ = family
    assert _exclude(client, a, "nope").status_code == 404
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    assert _exclude(client, a, direct).status_code == 404
    gone = client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, headers=a).json()
    _set(gone["attachment"]["id"], "photo", "manual")
    client.delete(f"{MSG}/{gone['id']}", headers=a)
    assert _exclude(client, a, gone["attachment"]["id"]).status_code == 404


def test_cannot_remove_a_direct_room_photo_even_if_it_has_a_photo_row(client, family):
    a, b, _ = family
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _uid(client, b)}, headers=a
    ).json()
    direct = _send(client, a, room_id=room["id"])
    with (
        SessionLocal() as db
    ):  # 있어서는 안 되는 줄이 있어도 방 종류 검사로 막는다(줄 없음 404 와 구분)
        db.add(
            ChatPhotoCheck(
                attachment_id=direct,
                group_id=db.get(MessageAttachment, direct).group_id,
                status="photo",
                source="manual",
            )
        )
        db.commit()
    assert _exclude(client, a, direct).status_code == 404
    assert _row(direct).status == "photo" and _events(direct) == []


def test_remove_requires_login(client, family):
    a, _, _ = family
    att = _shown(client, a)
    assert client.post(f"{PHOTOS}/{att}/exclude").status_code in (401, 403)


def test_remove_database_error_is_503(client, family, monkeypatch):
    from sqlalchemy.exc import OperationalError

    a, _, _ = family
    att = _shown(client, a)

    def boom(*args, **kwargs):
        raise OperationalError("update", {}, Exception("db down"))

    monkeypatch.setattr(checks, "exclude_photo", boom)
    r = _exclude(client, a, att)
    assert r.status_code == 503 and r.json()["code"] == "photo_checks_unavailable"


def test_removed_photo_stays_in_chat(client, family):
    a, _, _ = family
    att = _shown(client, a)
    _exclude(client, a, att)
    assert client.get(f"{PHOTOS}/{att}?size=thumb", headers=a).status_code == 200


# ---------- 뺀 사진 목록과 다시 넣기 ----------


def test_removed_photo_is_not_in_review_list_but_in_excluded_list(client, family):
    a, b, _ = family
    removed = _shown(client, a)
    unsure = _send(client, a)
    _set(unsure, "unsure")
    theirs = _shown(client, b)
    _exclude(client, a, removed)
    _exclude(client, b, theirs)
    review = _mine(client, a).json()
    assert [i["attachment_id"] for i in review["items"]] == [
        unsure
    ]  # 뺀 사진은 확인 필요에 다시 뜨지 않는다
    assert review["needs_review_count"] == 1
    excluded = _mine(client, a, kind="excluded").json()
    assert [(i["attachment_id"], i["status"]) for i in excluded["items"]] == [(removed, "excluded")]
    assert excluded["needs_review_count"] == 1
    # 다른 가족 구성원이 뺀 사진은 내 목록에 없다
    assert [i["attachment_id"] for i in _mine(client, b, kind="excluded").json()["items"]] == [
        theirs
    ]


def test_excluded_list_rejects_unknown_kind(client, family):
    a, _, _ = family
    assert _mine(client, a, kind="all").status_code == 422


def test_uploader_can_put_a_removed_photo_back_with_acknowledgement(client, family):
    a, b, _ = family
    att = _shown(client, a)
    _exclude(client, a, att)
    r = _confirm(client, a, att)
    assert r.status_code == 200 and r.json() == {"status": "photo", "source": "manual"}
    assert att in _ids(client, b)
    assert [(e.from_status, e.to_status) for e in _events(att)] == [
        ("photo", "excluded"),
        ("excluded", "photo"),
    ]
    no_ack = client.post(f"{PHOTOS}/{att}/check", json={**BODY, "acknowledge": False}, headers=a)
    assert no_ack.status_code == 422  # 다시 넣을 때도 안내 확인란이 필요하다


def test_put_back_by_someone_else_is_404(client, family):
    a, b, _ = family
    att = _shown(client, a)
    _exclude(client, a, att)
    assert _confirm(client, b, att).status_code == 404
    assert _row(att).status == "excluded"


# ---------- 다른 규칙과의 상호작용 ----------


def test_late_auto_result_cannot_bring_a_removed_photo_back_or_change_it(client, family):
    a, _, _ = family
    att = _shown(client, a)
    _exclude(client, a, att)
    for status in ("document", "unsure", "failed"):
        assert checks.record_auto(SessionLocal(), _row(att).group_id, att, status) is False
    assert _row(att).status == "excluded"
    assert att not in _ids(client, a)


def test_saving_a_removed_photo_as_document_still_works(client, family):
    a, _, _ = family
    att = _shown(client, a)
    _exclude(client, a, att)
    with SessionLocal() as db:
        checks.mark_document_manual(db, _row(att).group_id, att, _uid(client, a))
    assert _row(att).status == "document"
    r = _confirm(client, a, att)
    assert r.status_code == 409 and r.json()["code"] == "document_to_photo_blocked"


def test_timeline_requests_are_rate_limited_separately_from_checks(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(pcs, "TIMELINE_LIMIT", 2)
    assert _timeline(client, a).status_code == 200
    assert _timeline(client, a).status_code == 200
    r = _timeline(client, a)
    assert r.status_code == 429 and r.json()["code"] == "too_many_checks"
    assert (
        _mine(client, a).status_code == 200
    )  # 타임라인을 많이 봐도 확인 필요 조회는 막히지 않는다
