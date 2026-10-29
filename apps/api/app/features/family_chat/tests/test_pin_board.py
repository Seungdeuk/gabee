"""게시판(고정 메시지): 올릴 때 본문 사본을 저장해 원본이 지워져도 유지되고, 사용자마다 "나만 숨기기"를 따로 할 수 있다."""

import httpx
import pytest
from sqlalchemy import func, select

from app.features.family_chat import pin_service
from app.features.family_chat.models import ChatPinHide, ChatPinnedMessage, Message
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PINS = "/family-chat/pins"
MSG = "/family-chat/messages"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
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


def _send(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _pin(client, headers, message_id, room_id=None):
    body = {"message_id": message_id}
    if room_id is not None:
        body["room_id"] = room_id
    return client.post(PINS, json=body, headers=headers)


def _items(client, headers, room_id=None):
    params = {} if room_id is None else {"room_id": room_id}
    r = client.get(PINS, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {i["message_id"]: i for i in r.json()["items"]}


def _hide(client, headers, message_id, room_id=None):
    params = {"room_id": room_id} if room_id else None
    return client.put(f"{PINS}/{message_id}/hide", params=params, headers=headers)


def _show(client, headers, message_id, room_id=None):
    params = {"room_id": room_id} if room_id else None
    return client.delete(f"{PINS}/{message_id}/hide", params=params, headers=headers)


def _delete_msg(client, headers, message_id):
    r = client.delete(f"{MSG}/{message_id}", headers=headers)
    assert r.status_code == 200, r.text


# ── 본문 사본 ──────────────────────────────────────────────────────


def test_pin_survives_deleting_the_original_message(client, family):
    a, b, _ = family
    mid = _send(client, a, "토요일 할머니 댁 모임")
    assert _pin(client, b, mid).status_code == 200
    _delete_msg(client, a, mid)  # 보낸 사람이 원본을 지운다
    for headers in (a, b):
        item = _items(client, headers)[mid]
        assert item["text"] == "토요일 할머니 댁 모임"  # 게시판에는 그대로 남는다
        assert item["message_deleted"] is True
        assert item["user_name"] == "지민"


def test_live_pin_is_not_marked_deleted(client, family):
    a, _, _ = family
    mid = _send(client, a, "그대로인 공지")
    r = _pin(client, a, mid)
    assert r.json()["item"]["message_deleted"] is False and r.json()["item"]["hidden"] is False
    assert _items(client, a)[mid]["message_deleted"] is False


def test_pin_text_is_the_saved_copy_not_the_live_message(client, family):
    a, _, _ = family
    mid = _send(client, a, "올릴 때의 문구")
    assert _pin(client, a, mid).status_code == 200
    with SessionLocal() as db:
        db.get(Message, mid).text = "나중에 바뀐 문구"  # 원본이 어떻게 바뀌어도(예: 정리 작업)
        db.commit()
    assert _items(client, a)[mid]["text"] == "올릴 때의 문구"


def test_old_pin_without_copy_falls_back_to_message_text(client, family):
    """사본 컬럼이 생기기 전에 올린 공지(text 가 비어 있음)도 원본 본문으로 보인다."""
    a, _, _ = family
    mid = _send(client, a, "옛 공지")
    assert _pin(client, a, mid).status_code == 200
    with SessionLocal() as db:
        db.execute(ChatPinnedMessage.__table__.update().values(text=None))
        db.commit()
    assert _items(client, a)[mid]["text"] == "옛 공지"


def test_unpin_removes_the_saved_copy(client, family):
    a, _, _ = family
    mid = _send(client, a, "곧 내릴 공지")
    assert _pin(client, a, mid).status_code == 200
    assert client.delete(f"{PINS}/{mid}", headers=a).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPinnedMessage)) == 0


# ── 나만 숨기기 ───────────────────────────────────────────────────


def test_hide_is_per_user(client, trio):
    a, b, c = trio
    mid = _send(client, a, "공지입니다")
    assert _pin(client, a, mid).status_code == 200
    r = _hide(client, b, mid)
    assert r.status_code == 200 and r.json()["hidden"] is True and r.json()["message_id"] == mid
    assert _items(client, b)[mid]["hidden"] is True  # 내 화면에서는 숨김
    assert _items(client, a)[mid]["hidden"] is False  # 다른 가족은 그대로
    assert _items(client, c)[mid]["hidden"] is False


def test_hide_and_show_are_idempotent(client, family):
    a, _, _ = family
    mid = _send(client, a, "공지")
    _pin(client, a, mid)
    assert _hide(client, a, mid).status_code == 200
    assert _hide(client, a, mid).json()["hidden"] is True  # 두 번 숨겨도 같은 결과
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPinHide)) == 1
    assert _show(client, a, mid).json()["hidden"] is False
    assert _show(client, a, mid).json()["hidden"] is False  # 숨기지 않았어도 같은 결과
    assert _items(client, a)[mid]["hidden"] is False


def test_hide_requires_an_existing_pin(client, family):
    a, _, _ = family
    mid = _send(client, a, "고정하지 않은 메시지")
    assert _hide(client, a, mid).status_code == 404
    assert _hide(client, a, 999999).status_code == 404
    assert _show(client, a, mid).status_code == 404


def test_hide_respects_room_access_and_family_isolation(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "둘만의 공지", room_id=room)
    assert _pin(client, a, mid, room_id=room).status_code == 200
    assert (
        _hide(client, c, mid, room_id=room).status_code == 404
    )  # 참여자가 아니면 방이 없는 것처럼
    assert _hide(client, other_family, mid, room_id=room).status_code == 404
    assert _hide(client, b, mid, room_id=room).status_code == 200
    assert client.put(f"{PINS}/{mid}/hide").status_code == 401


def test_unpin_and_replacement_clear_hides_so_repin_starts_visible(client, family):
    a, b, _ = family
    first = _send(client, a, "첫 공지")
    _pin(client, a, first)
    assert _hide(client, b, first).status_code == 200
    # 내렸다가 다시 올리면 새 공지라 숨김이 남아 있지 않다
    assert client.delete(f"{PINS}/{first}", headers=a).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPinHide)) == 0
    assert _pin(client, a, first).status_code == 200
    assert _items(client, b)[first]["hidden"] is False
    # 3번째를 올려 가장 오래된 공지가 자동으로 내려갈 때도 그 공지의 숨김을 함께 지운다
    assert _hide(client, b, first).status_code == 200
    _pin(client, a, _send(client, a, "둘째"))
    third = _pin(client, a, _send(client, a, "셋째")).json()
    assert third["replaced_message_id"] == first
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ChatPinHide)) == 0


def test_pinning_deleted_message_is_rejected(client, family):
    a, b, _ = family
    mid = _send(client, a, "지운 메시지")
    _delete_msg(client, a, mid)
    r = _pin(client, b, mid)
    assert r.status_code == 400 and r.json()["code"] == "not_pinnable"


def test_hidden_flag_is_false_when_pinning(client, family):
    a, _, _ = family
    mid = _send(client, a, "새 공지")
    body = _pin(client, a, mid).json()
    assert body["item"]["hidden"] is False and body["already_pinned"] is False
