"""고정 메시지(공지): 고정·해제, 멱등, 방당 최대 2개 자동 교체, 텍스트만, 모든 구성원 권한, 방 격리, 제한, 로그."""

import io
import logging
import threading

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from app.features.family_chat import pin_repository, pin_service
from app.features.family_chat.models import ChatPinnedMessage, Message, MessageAttachment
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PINS = "/family-chat/pins"
MSG = "/family-chat/messages"
PHOTOS = "/family-chat/photos"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """한도는 시험마다 새로 세고, 사진은 임시 폴더에. 고정은 AI·외부를 부르지 않는다."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    pin_service.limiter.reset()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    yield
    pin_service.limiter.reset()


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _direct(client, headers, peer_id):
    r = client.post(DIRECT_ROOM, json={"user_id": peer_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _send(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _photo(client, headers, room_id=None):
    out = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 30, 30)).save(out, format="JPEG")
    form = {"room_id": room_id} if room_id else None
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, data=form, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _pin(client, headers, message_id, room_id=None):
    body = {"message_id": message_id}
    if room_id is not None:
        body["room_id"] = room_id
    return client.post(PINS, json=body, headers=headers)


def _pins(client, headers, room_id=None):
    params = {} if room_id is None else {"room_id": room_id}
    return client.get(PINS, params=params, headers=headers)


def _list_ids(client, headers, room_id=None):
    r = _pins(client, headers, room_id)
    assert r.status_code == 200, r.text
    return [i["message_id"] for i in r.json()["items"]]


def _count_rows():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(ChatPinnedMessage))


def test_pin_and_unpin_family_room(client, family):
    a, b, _ = family
    m = _send(client, a, "이번 주 토요일 할머니 댁")
    r = _pin(client, b, m)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_pinned"] is False and body["replaced_message_id"] is None
    item = body["item"]
    assert item["message_id"] == m and item["text"] == "이번 주 토요일 할머니 댁"
    assert item["text_truncated"] is False
    assert item["user_name"] == "지민" and item["pinned_by_name"] == "수진"
    assert item["pinned_by"] == _uid(client, b) and item["user_id"] == _uid(client, a)
    assert item["created_at"] and item["pinned_at"]
    listed = _pins(client, a).json()["items"]
    assert [i["message_id"] for i in listed] == [m]
    assert client.delete(f"{PINS}/{m}", headers=a).status_code == 204
    assert _list_ids(client, a) == []
    # 메시지는 그대로 남는다
    assert [x["id"] for x in client.get(MSG, headers=a).json()] == [m]
    assert client.delete(f"{PINS}/{m}", headers=a).status_code == 404


def test_pin_in_direct_room(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    m = _send(client, a, "둘만의 약속", room)
    assert _pin(client, b, m, room).status_code == 200
    assert _list_ids(client, a, room) == [m]
    assert _list_ids(client, a) == []  # 가족 전체방에는 보이지 않는다
    assert client.delete(f"{PINS}/{m}", params={"room_id": room}, headers=a).status_code == 204
    assert _list_ids(client, b, room) == []


def test_pin_is_idempotent_and_keeps_order(client, family):
    a, b, _ = family
    m1 = _send(client, a, "첫째")
    m2 = _send(client, a, "둘째")
    assert _pin(client, a, m1).status_code == 200
    first = _pins(client, a).json()["items"][0]["pinned_at"]  # (SQLite 는 시간대 표시가 빠진다)
    assert _pin(client, a, m2).status_code == 200
    again = _pin(client, b, m1)
    assert again.status_code == 200
    body = again.json()
    assert body["already_pinned"] is True and body["replaced_message_id"] is None
    assert body["item"]["pinned_at"] == first  # 시각은 그대로
    assert body["item"]["pinned_by_name"] == "지민"  # 처음 고정한 사람 그대로
    assert _list_ids(client, a) == [m2, m1]  # 순서 불변
    assert _count_rows() == 2


def test_third_pin_replaces_oldest(client, family):
    a, b, _ = family
    m1, m2, m3, m4 = (_send(client, a, f"공지 {i}") for i in range(4))
    assert _pin(client, a, m1).json()["replaced_message_id"] is None
    assert _pin(client, b, m2).json()["replaced_message_id"] is None
    r = _pin(client, a, m3)
    assert r.status_code == 200 and r.json()["replaced_message_id"] == m1
    assert r.json()["already_pinned"] is False
    assert _list_ids(client, a) == [m3, m2]
    assert _count_rows() == 2
    assert _pin(client, b, m4).json()["replaced_message_id"] == m2
    assert _list_ids(client, b) == [m4, m3]
    # 밀려난 메시지는 지워지지 않았다
    assert {x["id"] for x in client.get(MSG, headers=a).json()} == {m1, m2, m3, m4}


def test_list_returns_only_latest_two_newest_first(client, family):
    a, _, _ = family
    ids = [_send(client, a, f"공지 {i}") for i in range(3)]
    for m in ids:
        assert _pin(client, a, m).status_code == 200
    r = _pins(client, a).json()["items"]
    assert [i["message_id"] for i in r] == [ids[2], ids[1]]


def test_long_text_is_truncated_without_ellipsis(client, family):
    a, _, _ = family
    long = "가" * 250
    m = _send(client, a, long)
    item = _pin(client, a, m).json()["item"]
    assert item["text"] == "가" * 200 and item["text_truncated"] is True
    exact = _send(client, a, "나" * 200)
    item = _pin(client, a, exact).json()["item"]
    assert item["text"] == "나" * 200 and item["text_truncated"] is False


def test_only_text_messages_are_pinnable(client, family):
    a, _, _ = family
    photo = _photo(client, a)
    r = _pin(client, a, photo)
    assert r.status_code == 400 and r.json()["code"] == "not_pinnable"
    with SessionLocal() as db:  # 서버가 공백만 있는 글을 막지만, 예전 데이터를 가정해 직접 만든다
        group_id = db.scalar(select(Message.group_id).limit(1))
        empty = Message(group_id=group_id, user_id=_uid(client, a), text="   ")
        db.add(empty)
        db.commit()
        empty_id = empty.id
    r = _pin(client, a, empty_id)
    assert r.status_code == 400 and r.json()["code"] == "not_pinnable"
    assert _count_rows() == 0


def test_text_message_with_attachment_is_not_pinnable(client, family):
    a, _, _ = family
    m = _send(client, a, "글도 있고 첨부도 있는 메시지")
    with SessionLocal() as db:
        msg = db.get(Message, m)
        db.add(
            MessageAttachment(
                message_id=m,
                group_id=msg.group_id,
                room_id=msg.room_id,
                path="x.jpg",
                thumb_path="x_t.jpg",
                width=1,
                height=1,
                size_bytes=1,
            )
        )
        db.commit()
    r = _pin(client, a, m)
    assert r.status_code == 400 and r.json()["code"] == "not_pinnable"
    assert _count_rows() == 0


def _unpin_after_commit(_unused=None):
    """고정 요청의 commit 직후 다른 구성원이 그 방의 고정을 모두 해제한 상황을 만든다."""
    state = {"on": True}

    def after_commit(_session):
        if not state["on"]:
            return
        state["on"] = False  # 해제용 세션의 commit 에서 다시 부르지 않는다
        with SessionLocal() as other:
            other.execute(delete(ChatPinnedMessage))
            other.commit()

    event.listen(Session, "after_commit", after_commit)
    return lambda: event.remove(Session, "after_commit", after_commit)


def test_unpin_right_after_pin_commit_is_not_a_500(client, family):
    a, b, _ = family
    m = _send(client, a, "곧 풀릴 공지")
    off = _unpin_after_commit(None)
    try:
        r = _pin(client, a, m)
    finally:
        off()
    assert r.status_code == 200, r.text
    assert r.json()["item"]["message_id"] == m and r.json()["already_pinned"] is False
    assert _count_rows() == 0  # 끼어든 해제가 적용됐다


def test_unpin_right_after_idempotent_pin_commit_is_not_a_500(client, family):
    a, b, _ = family
    m = _send(client, a, "이미 고정된 공지")
    assert _pin(client, a, m).status_code == 200
    off = _unpin_after_commit(None)
    try:
        r = _pin(client, b, m)
    finally:
        off()
    assert r.status_code == 200, r.text
    assert r.json()["already_pinned"] is True and r.json()["item"]["pinned_by_name"] == "지민"


def test_pin_response_does_not_requery_after_commit(client, family, monkeypatch):
    a, b, _ = family
    m = _send(client, a, "다시 조회하지 않는 공지")

    def boom(*args, **kwargs):
        raise AssertionError("commit 뒤에 고정을 다시 조회하면 안 돼요")

    monkeypatch.setattr(pin_repository, "pin_rows", boom)
    first = _pin(client, a, m)
    again = _pin(client, b, m)
    assert first.status_code == 200 and first.json()["item"]["pinned_by_name"] == "지민"
    assert again.status_code == 200 and again.json()["already_pinned"] is True


def test_message_from_other_room_or_missing_is_invalid(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    in_direct = _send(client, a, "1:1 메시지", room)
    in_family = _send(client, a, "가족 메시지")
    r = _pin(client, a, in_direct)  # 가족 전체방에 1:1 메시지를
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    r = _pin(client, a, in_family, room)  # 1:1 방에 가족방 메시지를
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    r = _pin(client, a, 999999)
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    assert _count_rows() == 0


def test_legacy_message_without_room_is_pinnable_in_family_room(client, family):
    a, _, _ = family
    m = _send(client, a, "옛 메시지")
    with SessionLocal() as db:
        msg = db.get(Message, m)
        msg.room_id = None  # 방 구조가 생기기 전의 메시지
        db.commit()
    assert _pin(client, a, m).status_code == 200
    assert _list_ids(client, a) == [m]


def test_every_member_can_pin_and_unpin_family_room(client, trio):
    a, b, c = trio
    m = _send(client, a, "모두가 볼 공지")
    assert _pin(client, b, m).status_code == 200  # 쓴 사람이 아니어도
    assert client.delete(f"{PINS}/{m}", headers=c).status_code == 204  # 고정한 사람이 아니어도
    assert _pin(client, c, m).status_code == 200
    assert client.delete(f"{PINS}/{m}", headers=a).status_code == 204


def test_direct_peer_can_unpin_what_other_pinned(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    m = _send(client, a, "상대도 내릴 수 있는 공지", room)
    assert _pin(client, a, m, room).status_code == 200
    assert client.delete(f"{PINS}/{m}", params={"room_id": room}, headers=b).status_code == 204
    assert _list_ids(client, a, room) == []


def test_isolation_other_family(client, family, other_family):
    a, _, _ = family
    out = other_family
    m = _send(client, a, "우리 가족 공지")
    assert _pin(client, a, m).status_code == 200
    # 다른 가족은 자기 가족방을 쓸 뿐 우리 메시지에 접근하지 못한다
    assert _list_ids(client, out) == []
    r = _pin(client, out, m)
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    assert client.delete(f"{PINS}/{m}", headers=out).status_code == 404
    assert _list_ids(client, a) == [m]
    # 우리 방 id 를 직접 줘도 404
    room_id = client.get("/family-chat/rooms", headers=a).json()[0]["id"]
    assert _pins(client, out, room_id).status_code == 404
    assert _pin(client, out, m, room_id).status_code == 404
    assert client.delete(f"{PINS}/{m}", params={"room_id": room_id}, headers=out).status_code == 404
    assert _list_ids(client, a) == [m]


def test_isolation_direct_room_non_participant(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    m = _send(client, a, "둘만 아는 공지", room)
    assert _pin(client, b, m, room).status_code == 200
    for r in (
        _pins(client, c, room),
        _pin(client, c, m, room),
        client.delete(f"{PINS}/{m}", params={"room_id": room}, headers=c),
    ):
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    # 없는 방과 같은 응답이라 존재 단서가 없다
    missing = _pins(client, c, "nosuchroom")
    assert missing.status_code == 404 and missing.json() == _pins(client, c, room).json()
    assert _list_ids(client, a, room) == [m]
    # c 의 가족방에는 영향이 없다
    assert _list_ids(client, c) == []


def test_unauthenticated(client):
    assert client.get(PINS).status_code == 401
    assert client.post(PINS, json={"message_id": 1}).status_code == 401
    assert client.delete(f"{PINS}/1").status_code == 401


def test_write_rate_limit(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(pin_service, "WRITE_LIMIT", 3)
    m = _send(client, a, "자주 누르는 공지")
    assert _pin(client, a, m).status_code == 200
    assert client.delete(f"{PINS}/{m}", headers=a).status_code == 204
    assert _pin(client, a, m).status_code == 200
    r = client.delete(f"{PINS}/{m}", headers=a)
    assert r.status_code == 429 and r.json()["code"] == "too_many_requests"
    assert int(r.headers["Retry-After"]) >= 1
    assert _pin(client, a, m).status_code == 429
    assert _list_ids(client, a) == [m]  # 조회는 제한이 없고, 막힌 해제는 적용되지 않았다
    # 다른 사용자는 따로 센다
    assert client.delete(f"{PINS}/{m}", headers=b).status_code == 204


def test_no_text_in_logs(client, family, caplog):
    a, b, _ = family
    m = _send(client, a, "비밀스러운공지문구 포함 메시지")
    m2 = _send(client, a, "또다른비밀문구")
    with caplog.at_level(logging.DEBUG):
        assert _pin(client, b, m).status_code == 200
        assert _pins(client, a).status_code == 200
        assert _pin(client, b, m2).status_code == 200
        assert client.delete(f"{PINS}/{m}", headers=a).status_code == 204
        assert client.delete(f"{PINS}/{m}", headers=a).status_code == 404
    assert "비밀스러운공지문구" not in caplog.text and "또다른비밀문구" not in caplog.text


def test_pinned_text_comes_from_message_join(client, family):
    a, _, _ = family
    m = _send(client, a, "원본 글")
    assert _pin(client, a, m).status_code == 200
    with SessionLocal() as db:
        columns = {c.name for c in ChatPinnedMessage.__table__.columns}
        assert "text" not in columns  # 본문을 복사해 두지 않는다
        db.get(Message, m).text = "고친 글"
        db.commit()
    assert _pins(client, a).json()["items"][0]["text"] == "고친 글"
    assert [x["id"] for x in client.get(MSG, headers=a).json()] == [m]


def test_concurrent_third_pins_never_leave_more_than_two(client, family):
    """같은 방에서 여러 요청이 동시에 고정해도 2개를 넘지 않는다(서비스 직접 호출, 스레드별 세션).
    SQLite 에서는 쓰기가 직렬이라 행 잠금(FOR UPDATE)까지는 검증하지 못한다 - PostgreSQL 은 별도 스크립트로 확인."""
    from app.features.family_chat import pin_service as svc
    from app.features.family_group.models import User

    a, _, group = family
    a_id = _uid(client, a)
    ids = [_send(client, a, f"경쟁 {i}") for i in range(6)]
    errors: list[BaseException] = []
    done: list[int] = []
    barrier = threading.Barrier(len(ids))

    def work(message_id: int) -> None:
        try:
            with SessionLocal() as db:
                user = db.get(User, a_id)
                barrier.wait(timeout=10)
                for _ in range(5):  # SQLite 가 잠깐 잠겨 있으면 다시 시도
                    try:
                        svc.pin(db, user, group["id"], message_id, None)
                        done.append(message_id)
                        return
                    except Exception as e:  # noqa: BLE001
                        db.rollback()
                        if "locked" not in str(e).lower():
                            raise
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=work, args=(m,)) for m in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert sorted(done) == sorted(ids)  # 모든 요청이 (잠김 재시도 끝에) 성공해야 한다
    assert _count_rows() == 2
    assert len(_list_ids(client, a)) == 2
