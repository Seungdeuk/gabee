"""메시지-일정·할 일 연결: 생성·멱등, 목록(최신순·필터·limit), 삭제(만든 사람만), 검증, 방 격리, 제한, 로그."""

import io
import logging
from urllib.parse import quote

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.features.family_chat import link_repository, link_service
from app.features.family_chat.models import ChatMessageLink, Message
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

LINKS = "/family-chat/links"
MSG = "/family-chat/messages"
PHOTOS = "/family-chat/photos"
TODOS = "/family-chat/todos"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """한도는 시험마다 새로 세고, 사진은 임시 폴더에. 연결은 AI·외부를 부르지 않는다."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    link_service.limiter.reset()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    yield
    link_service.limiter.reset()


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


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _todo(client, headers, title="우유 사기"):
    r = client.post(TODOS, json={"title": title, "source": "chat"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _link(client, headers, message_id, target_id="ev1", kind="event", room_id=None, **extra):
    body = {
        "message_id": message_id,
        "kind": kind,
        "target_id": target_id,
        "title": "할머니 댁 방문",
        **extra,
    }
    if room_id is not None:
        body["room_id"] = room_id
    return client.post(LINKS, json=body, headers=headers)


def _links(client, headers, **params):
    return client.get(LINKS, params=params, headers=headers)


def _items(client, headers, **params):
    r = _links(client, headers, **params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _count_rows():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(ChatMessageLink))


def test_create_event_link_and_list(client, family):
    a, b, _ = family
    m = _send(client, a, "이번 주 토요일 오후 3시에 할머니 댁")
    r = _link(client, b, m, date="2026-11-07", time="15:00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "event" and body["target_id"] == "ev1"
    assert body["title"] == "할머니 댁 방문" and body["date"] == "2026-11-07"
    assert body["time"] == "15:00"
    assert body["message_id"] == m and body["message_text"] == "이번 주 토요일 오후 3시에 할머니 댁"
    assert body["message_user_name"] == "지민" and body["created_by_name"] == "수진"
    assert body["created_by"] == _uid(client, b) and body["created_at"] and body["room_id"]
    listed = _items(client, a)
    assert [i["id"] for i in listed] == [body["id"]]


def test_create_todo_link_without_date(client, family):
    a, _, _ = family
    m = _send(client, a, "우유 좀 사다 줘")
    t = _todo(client, a)
    r = _link(client, a, m, target_id=t, kind="todo")
    assert r.status_code == 201, r.text
    assert r.json()["date"] is None and r.json()["time"] is None


def test_create_is_idempotent(client, family):
    a, b, _ = family
    m = _send(client, a, "중복 등록")
    first = _link(client, a, m)
    assert first.status_code == 201
    again = _link(client, b, m, title="다른 제목")
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["title"] == "할머니 댁 방문"  # 기존 것 그대로
    assert again.json()["created_by_name"] == "지민"
    assert _count_rows() == 1
    # 대상이 다르면 별개의 연결
    assert _link(client, a, m, target_id="ev2").status_code == 201
    assert _count_rows() == 2


def test_list_newest_first_filter_and_limit(client, family):
    a, _, _ = family
    m = _send(client, a, "여러 개 등록")
    t = _todo(client, a)
    ids = [
        _link(client, a, m, target_id="ev1").json()["id"],
        _link(client, a, m, target_id=t, kind="todo").json()["id"],
        _link(client, a, m, target_id="ev2").json()["id"],
    ]
    assert [i["id"] for i in _items(client, a)] == ids[::-1]
    assert [i["id"] for i in _items(client, a, kind="event")] == [ids[2], ids[0]]
    assert [i["id"] for i in _items(client, a, kind="todo")] == [ids[1]]
    assert [i["id"] for i in _items(client, a, limit=2)] == [ids[2], ids[1]]
    assert [i["id"] for i in _items(client, a, kind="event", target_id="ev1")] == [ids[0]]
    assert _items(client, a, target_id="nothing") == []
    for bad in ({"limit": 0}, {"limit": 101}, {"kind": "memo"}):
        assert _links(client, a, **bad).status_code == 422


def test_delete_only_creator(client, trio):
    a, b, c = trio
    m = _send(client, a, "지울 연결")
    link = _link(client, a, m).json()["id"]
    r = client.delete(f"{LINKS}/{link}", headers=b)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert _count_rows() == 1
    assert client.delete(f"{LINKS}/{link}", headers=a).status_code == 204
    assert _items(client, c) == []
    assert client.delete(f"{LINKS}/{link}", headers=a).status_code == 404
    assert client.delete(f"{LINKS}/nosuch", headers=a).status_code == 404
    # 메시지는 그대로 남는다
    assert [x["id"] for x in client.get(MSG, headers=a).json()] == [m]


def test_link_in_direct_room(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    m = _send(client, a, "둘만의 약속", room)
    r = _link(client, b, m, room_id=room)
    assert r.status_code == 201 and r.json()["room_id"] == room
    assert [i["message_id"] for i in _items(client, a, room_id=room)] == [m]
    assert _items(client, a) == []  # 가족 전체방에는 보이지 않는다
    link = r.json()["id"]
    assert client.delete(f"{LINKS}/{link}", params={"room_id": room}, headers=a).status_code == 403
    assert client.delete(f"{LINKS}/{link}", params={"room_id": room}, headers=b).status_code == 204


def test_message_must_be_text_message_of_this_room(client, trio):
    a, b, _ = trio
    room = _direct(client, a, _uid(client, b))
    in_direct = _send(client, a, "1:1 메시지", room)
    in_family = _send(client, a, "가족 메시지")
    photo = _photo(client, a)
    for r in (
        _link(client, a, in_direct),  # 가족 전체방에 1:1 메시지를
        _link(client, a, in_family, room_id=room),  # 1:1 방에 가족방 메시지를
        _link(client, a, 999999),
        _link(client, a, photo),
    ):
        assert r.status_code == 400 and r.json()["code"] == "invalid_message", r.text
    assert _count_rows() == 0


def test_legacy_message_without_room_is_linkable(client, family):
    a, _, _ = family
    m = _send(client, a, "옛 메시지")
    with SessionLocal() as db:
        db.get(Message, m).room_id = None  # 방 구조가 생기기 전의 메시지
        db.commit()
    assert _link(client, a, m).status_code == 201
    assert [i["message_id"] for i in _items(client, a)] == [m]


def test_todo_target_must_exist_in_group(client, family, other_family):
    a, _, _ = family
    out = other_family
    m = _send(client, a, "할 일 연결")
    r = _link(client, a, m, target_id="nosuchtodo", kind="todo")
    assert r.status_code == 400 and r.json()["code"] == "invalid_target"
    foreign = _todo(client, out, "다른 가족 할 일")
    r = _link(client, a, m, target_id=foreign, kind="todo")
    assert r.status_code == 400 and r.json()["code"] == "invalid_target"
    assert _count_rows() == 0
    # event 는 일정 기능을 검증하지 않고 복사본만 저장한다
    assert _link(client, a, m, target_id="없는일정id", kind="event").status_code == 201


def test_title_validation(client, family):
    a, _, _ = family
    m = _send(client, a, "제목 검사")
    assert _link(client, a, m, title="   ").status_code == 422
    assert _link(client, a, m, title="").status_code == 422
    assert _link(client, a, m, title="가" * 121).status_code == 422
    assert _link(client, a, m, title="가" * 300).status_code == 422
    assert _count_rows() == 0
    r = _link(client, a, m, title="  병원   예약  ")
    assert r.status_code == 201 and r.json()["title"] == "병원 예약"
    assert _link(client, a, m, target_id="ev9", title="나" * 120).status_code == 201


def test_body_validation(client, family):
    a, _, _ = family
    m = _send(client, a, "본문 검사")
    assert _link(client, a, m, kind="memo").status_code == 422
    assert _link(client, a, m, time="25:00").status_code == 422
    assert _link(client, a, m, time="9:00").status_code == 422
    assert _link(client, a, m, date="내일").status_code == 422
    assert _link(client, a, m, target_id="").status_code == 422
    assert _link(client, a, m, target_id="x" * 33).status_code == 422
    assert _count_rows() == 0


def test_room_link_limit(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(link_repository, "MAX_LINKS", 3)
    m = _send(client, a, "많이 등록")
    for i in range(3):
        assert _link(client, a, m, target_id=f"ev{i}").status_code == 201
    r = _link(client, a, m, target_id="ev3")
    assert r.status_code == 400 and r.json()["code"] == "too_many_links"
    assert _link(client, a, m, target_id="ev0").status_code == 200  # 이미 있는 연결은 멱등
    assert _count_rows() == 3


def test_isolation_other_family(client, family, other_family):
    a, _, _ = family
    out = other_family
    m = _send(client, a, "우리 가족 연결")
    link = _link(client, a, m).json()["id"]
    room_id = client.get("/family-chat/rooms", headers=a).json()[0]["id"]
    assert _items(client, out) == []
    r = _link(client, out, m)  # 우리 메시지 id 를 줘도 다른 가족의 방에서는 없는 메시지
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    assert client.delete(f"{LINKS}/{link}", headers=out).status_code == 404
    # 우리 방 id 를 직접 줘도 404
    assert _links(client, out, room_id=room_id).status_code == 404
    assert _link(client, out, m, room_id=room_id).status_code == 404
    assert (
        client.delete(f"{LINKS}/{link}", params={"room_id": room_id}, headers=out).status_code
        == 404
    )
    assert [i["id"] for i in _items(client, a)] == [link]


def test_isolation_direct_room_non_participant(client, trio):
    a, b, c = trio
    room = _direct(client, a, _uid(client, b))
    m = _send(client, a, "둘만 아는 연결", room)
    link = _link(client, b, m, room_id=room).json()["id"]
    for r in (
        _links(client, c, room_id=room),
        _link(client, c, m, room_id=room),
        client.delete(f"{LINKS}/{link}", params={"room_id": room}, headers=c),
    ):
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    missing = _links(client, c, room_id="nosuchroom")  # 없는 방과 같은 응답이라 단서가 없다
    assert missing.status_code == 404 and missing.json() == _links(client, c, room_id=room).json()
    assert (
        client.delete(f"{LINKS}/{link}", params={"room_id": "nosuchroom"}, headers=c).status_code
        == 404
    )
    # 가족방 쪽에서 1:1 방의 연결 id 로 지우려 해도 404
    assert client.delete(f"{LINKS}/{link}", headers=a).status_code == 404
    assert [i["id"] for i in _items(client, a, room_id=room)] == [link]
    assert _items(client, c) == []


def test_unauthenticated(client):
    assert client.get(LINKS).status_code == 401
    body = {"message_id": 1, "kind": "event", "target_id": "x", "title": "t"}
    assert client.post(LINKS, json=body).status_code == 401
    assert client.delete(f"{LINKS}/1").status_code == 401


def test_write_rate_limit(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(link_service, "WRITE_LIMIT", 3)
    m = _send(client, a, "자주 누르는 연결")
    link = _link(client, a, m).json()["id"]
    assert client.delete(f"{LINKS}/{link}", headers=a).status_code == 204
    assert _link(client, a, m).status_code == 201
    r = _link(client, a, m, target_id="ev2")
    assert r.status_code == 429 and r.json()["code"] == "too_many_requests"
    assert int(r.headers["Retry-After"]) >= 1
    assert len(_items(client, a)) == 1  # 조회는 제한이 없고, 막힌 생성은 적용되지 않았다
    assert _link(client, b, m, target_id="ev2").status_code == 201  # 다른 사용자는 따로 센다


def test_no_text_in_logs(client, family, caplog):
    a, b, _ = family
    m = _send(client, a, "비밀스러운연결문구 포함 메시지")
    with caplog.at_level(logging.DEBUG):
        link = _link(client, b, m, title="비밀스러운제목").json()["id"]
        assert _links(client, a).status_code == 200
        assert _link(client, b, m, title="비밀스러운제목").status_code == 200
        assert client.delete(f"{LINKS}/{link}", headers=a).status_code == 403
        assert client.delete(f"{LINKS}/{link}", headers=b).status_code == 204
        assert client.delete(f"{LINKS}/{link}", headers=b).status_code == 404
    assert "비밀스러운연결문구" not in caplog.text and "비밀스러운제목" not in caplog.text


def test_message_text_comes_from_join_and_is_truncated(client, family):
    a, _, _ = family
    m = _send(client, a, "가" * 250)
    body = _link(client, a, m).json()
    assert body["message_text"] == "가" * 100
    with SessionLocal() as db:  # 본문은 복사 저장되지 않으므로 메시지가 바뀌면 그대로 따라온다
        assert "message_text" not in ChatMessageLink.__table__.c
        db.get(Message, m).text = "고친 글"
        db.commit()
    assert _items(client, a)[0]["message_text"] == "고친 글"


BAD_TEXTS = ["a\x00b", "a\x07b", "a\x1fb", "a\x7fb", "a\x85b"]


def test_control_chars_are_422_not_500(client, family, caplog, monkeypatch):
    monkeypatch.setattr(link_service, "WRITE_LIMIT", 10_000)
    a, _, _ = family
    m = _send(client, a, "제어문자 검사")
    link = _link(client, a, m, target_id="ok").json()["id"]
    with caplog.at_level(logging.DEBUG):
        for bad in BAD_TEXTS:
            tag = "비밀" + bad
            assert _link(client, a, m, title=tag).status_code == 422
            assert _link(client, a, m, target_id=tag).status_code == 422
            assert _link(client, a, m, kind="todo", target_id=tag).status_code == 422
            assert _link(client, a, m, room_id=tag).status_code == 422
            assert _links(client, a, room_id=tag).status_code == 422
            assert _links(client, a, target_id=tag).status_code == 422
            assert (
                client.delete(f"{LINKS}/{link}", params={"room_id": tag}, headers=a).status_code
                == 422
            )
            assert client.delete(f"{LINKS}/x{quote(bad)}y", headers=a).status_code == 422
    assert "비밀" not in caplog.text
    assert _count_rows() == 1
    # 탭·개행은 공백으로 정리된다
    r = _link(client, a, m, target_id="t2", title="병원\t예약\n내일")
    assert r.status_code == 201 and r.json()["title"] == "병원 예약 내일"


def test_invisible_only_title_is_422(client, family):
    a, _, _ = family
    m = _send(client, a, "보이지 않는 제목")
    for t in ("​", " ​‍ ", "﻿"):
        r = _link(client, a, m, title=t)
        assert r.status_code == 422 and r.json()["code"] == "invalid_title"
    assert _count_rows() == 0


def test_recreate_after_delete(client, family):
    a, _, _ = family
    m = _send(client, a, "지우고 다시")
    first = _link(client, a, m)
    assert first.status_code == 201
    assert client.delete(f"{LINKS}/{first.json()['id']}", headers=a).status_code == 204
    again = _link(client, a, m)
    assert again.status_code == 201 and again.json()["id"] != first.json()["id"]
    assert _count_rows() == 1
