"""대화 검색(글자 일치)과 messages 의 around_id: 일치 규칙, 이스케이프, 쪽 나누기, 권한 격리, 제한, 로그."""

import logging

import pytest
from sqlalchemy import select

from app.features.family_chat import search_service
from app.features.family_chat.models import FAMILY, ChatRoom, Message
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

SEARCH = "/family-chat/search"
MSG = "/family-chat/messages"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _reset_limiter():
    search_service.search_limiter.reset()
    yield
    search_service.search_limiter.reset()


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c, group


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


def _search(client, headers, q, **params):
    return client.get(SEARCH, params={"q": q, **params}, headers=headers)


def _ids(r):
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_matches_all_words_case_insensitive_newest_first(client, family):
    a, b, _ = family
    m1 = _send(client, a, "병원 예약 Tuesday 오후 세 시")
    _send(client, b, "병원 말고 학교 얘기")
    m3 = _send(client, b, "다음 주 tuesday 병원 예약 취소")
    r = _search(client, a, "예약  TUESDAY")
    assert _ids(r) == [m3, m1]  # 모든 낱말(AND)이 들어 있고 최신순, 대소문자 무시
    assert r.json()["next_before_id"] is None
    item = r.json()["items"][0]
    assert item["user_name"] == "수진" and item["room_kind"] == "family"
    assert item["peer_user_id"] is None and item["room_id"]
    assert item["text"] == "다음 주 tuesday 병원 예약 취소"


def test_substring_match_inside_word(client, family):
    a, _, _ = family
    m = _send(client, a, "소아과예약해뒀어")
    assert _ids(_search(client, a, "예약")) == [m]


@pytest.mark.parametrize("pattern", ["%", "_", "100%", "a_c", "\\"])
def test_wildcards_are_literal(client, family, pattern):
    a, _, _ = family
    literal = _send(client, a, f"특수 {pattern} 문자")
    _send(client, a, "abc 평범한 글 100원 xyz")
    _send(client, a, "일반 메시지")
    assert _ids(_search(client, a, pattern)) == [literal]


def test_photo_messages_excluded(client, family):
    a, _, group = family
    m = _send(client, a, "사진 말고 글")
    db = SessionLocal()
    room = db.scalar(
        select(ChatRoom).where(ChatRoom.group_id == group["id"], ChatRoom.kind == FAMILY)
    )
    db.add(Message(group_id=group["id"], room_id=room.id, user_id=_uid(client, a), text=""))
    db.commit()
    db.close()
    assert _ids(_search(client, a, "사진")) == [m]
    assert _ids(_search(client, a, "글", limit=50)) == [m]


def test_cursor_paging(client, family):
    a, _, _ = family
    sent = [_send(client, a, f"장보기 {i}") for i in range(5)]
    first = _search(client, a, "장보기", limit=2).json()
    assert [i["id"] for i in first["items"]] == [sent[4], sent[3]]
    assert first["next_before_id"] == sent[3]
    second = _search(client, a, "장보기", limit=2, before_id=first["next_before_id"]).json()
    assert [i["id"] for i in second["items"]] == [sent[2], sent[1]]
    third = _search(client, a, "장보기", limit=2, before_id=second["next_before_id"]).json()
    assert [i["id"] for i in third["items"]] == [sent[0]]
    assert third["next_before_id"] is None
    # 딱 limit 개로 끝나면 다음 쪽이 없다
    exact = _search(client, a, "장보기", limit=5).json()
    assert len(exact["items"]) == 5 and exact["next_before_id"] is None


def test_query_validation(client, family):
    a, _, _ = family
    for q in ("", "   ", "가" * 101):
        r = _search(client, a, q)
        assert r.status_code == 422 and r.json()["code"] == "invalid_query"
    assert _search(client, a, "가" * 100).status_code == 200
    assert _search(client, a, " 가 ").status_code == 200
    assert client.get(SEARCH, headers=a).status_code == 422  # q 없음
    assert _search(client, a, "x", limit=0).status_code == 422
    assert _search(client, a, "x", limit=51).status_code == 422
    assert _search(client, a, "x", before_id=0).status_code == 422


def test_rate_limit_429(client, family, monkeypatch):
    a, b, _ = family
    monkeypatch.setattr(search_service, "SEARCH_LIMIT", 3)
    for _i in range(3):
        assert _search(client, a, "x").status_code == 200
    r = _search(client, a, "x")
    assert r.status_code == 429 and r.json()["code"] == "too_many_searches"
    assert "Retry-After" in r.headers
    assert _search(client, b, "x").status_code == 200  # 사용자별 제한


def test_no_query_or_text_in_logs(client, family, caplog):
    a, _, _ = family
    _send(client, a, "비밀스러운검색어 포함 메시지")
    with caplog.at_level(logging.DEBUG):
        assert _search(client, a, "비밀스러운검색어").status_code == 200
    assert "비밀스러운검색어" not in caplog.text


def test_direct_rooms_isolation(client, trio):
    a, b, c, _ = trio
    b_id, c_id = (
        _uid(
            client,
            b,
        ),
        _uid(client, c),
    )
    ab = _direct(client, a, b_id)
    bc = _direct(client, b, c_id)
    fam = _send(client, a, "공통 가족 메시지 열쇠")
    in_ab = _send(client, a, "둘만 아는 열쇠", ab)
    in_bc = _send(client, b, "수진과 삼촌 열쇠", bc)

    # a: 가족방 + 나·수진 방. b-c 방은 안 보인다
    assert set(_ids(_search(client, a, "열쇠"))) == {fam, in_ab}
    assert set(_ids(_search(client, b, "열쇠"))) == {fam, in_ab, in_bc}
    assert set(_ids(_search(client, c, "열쇠"))) == {fam, in_bc}
    hit = next(i for i in _search(client, a, "열쇠").json()["items"] if i["id"] == in_ab)
    assert hit["room_kind"] == "direct" and hit["room_id"] == ab and hit["peer_user_id"] == b_id

    # room_id 지정: 내 방은 그 방만, 참여하지 않은 방은 404
    assert _ids(_search(client, a, "열쇠", room_id=ab)) == [in_ab]
    r = _search(client, a, "열쇠", room_id=bc)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert _search(client, a, "열쇠", room_id="nonexistent").status_code == 404


def test_other_family_never_visible(client, family, other_family):
    a, _, _ = family
    other = other_family
    mine = _send(client, a, "겹치는 단어 우리집")
    theirs = _send(client, other, "겹치는 단어 남의집")
    assert _ids(_search(client, a, "겹치는")) == [mine]
    assert _ids(_search(client, other, "겹치는")) == [theirs]
    other_room = client.get("/family-chat/rooms", headers=other).json()[0]["id"]
    assert _search(client, a, "겹치는", room_id=other_room).status_code == 404


def test_legacy_null_room_messages_belong_to_family_room(client, family):
    a, _, group = family
    db = SessionLocal()
    legacy = Message(
        group_id=group["id"], room_id=None, user_id=_uid(client, a), text="옛날 메시지 보물"
    )
    db.add(legacy)
    db.commit()
    legacy_id = legacy.id
    db.close()
    r = _search(client, a, "보물")
    assert _ids(r) == [legacy_id]
    family_room = client.get("/family-chat/rooms", headers=a).json()[0]
    assert r.json()["items"][0]["room_id"] == family_room["id"]
    assert r.json()["items"][0]["room_kind"] == "family"
    assert _ids(_search(client, a, "보물", room_id=family_room["id"])) == [legacy_id]


def test_search_requires_login_and_membership(client):
    r = client.get(SEARCH, params={"q": "x"})
    assert r.status_code == 401


# ── around_id ──────────────────────────────────────────


def _around(client, headers, around_id, **params):
    return client.get(MSG, params={"around_id": around_id, **params}, headers=headers)


def test_around_window_middle_and_edges(client, family):
    a, _, _ = family
    ids = [_send(client, a, f"메시지 {i}") for i in range(10)]
    mid = _around(client, a, ids[5], limit=4)
    assert [m["id"] for m in mid.json()] == ids[3:8]  # 앞 2 + 가운데 + 뒤 2, 오래된 순
    first = _around(client, a, ids[0], limit=4)
    assert [m["id"] for m in first.json()] == ids[0:3]
    last = _around(client, a, ids[9], limit=4)
    assert [m["id"] for m in last.json()] == ids[7:10]
    default = _around(client, a, ids[5])  # 기본 50 -> 앞뒤 25
    assert [m["id"] for m in default.json()] == ids


def test_around_single_message_room(client, family):
    a, _, _ = family
    only = _send(client, a, "하나뿐")
    assert [m["id"] for m in _around(client, a, only).json()] == [only]


def test_around_wrong_room_and_missing_message(client, trio):
    a, b, c, _ = trio
    ab = _direct(client, a, _uid(client, b))
    fam = _send(client, a, "가족방 글")
    other = _send(client, a, "둘만의 글", ab)
    r = _around(client, a, other)  # room_id 없음 = 가족 전체방인데 1:1 방 메시지
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    r = _around(client, a, 999999)
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    assert [m["id"] for m in _around(client, a, other, room_id=ab).json()] == [other]
    assert [m["id"] for m in _around(client, a, fam).json()] == [fam]
    # 참여하지 않은 1:1 방은 404
    assert _around(client, c, other, room_id=ab).status_code == 404


def test_around_conflicts_with_other_range_params(client, family):
    a, _, _ = family
    m = _send(client, a, "글")
    for extra in ({"latest": True}, {"before_id": 5}, {"after_id": 1}):
        r = _around(client, a, m, **extra)
        assert r.status_code == 400 and r.json()["code"] == "invalid_range", extra


def test_around_includes_photo_attachment_shape(client, family):
    a, _, _ = family
    m = _send(client, a, "글")
    body = _around(client, a, m).json()[0]
    assert "attachment" in body and body["attachment"] is None


# ── 검토 반영: 제어문자·경계·쪽 나누기 ───────────────────


@pytest.mark.parametrize("bad", ["a\x00b", "\x1f", "x\x07", "x\x85y", "\x7f"])
def test_control_characters_rejected_before_db(client, family, bad, caplog):
    a, _, _ = family
    with caplog.at_level(logging.DEBUG):
        r = _search(client, a, "비밀" + bad)
    assert r.status_code == 422 and r.json()["code"] == "invalid_query"
    assert "비밀" not in caplog.text


def test_tab_newline_and_fullwidth_space_are_whitespace(client, family):
    a, _, _ = family
    m = _send(client, a, "병원 예약 안내")
    assert _ids(_search(client, a, "병원\t예약")) == [m]
    assert _ids(_search(client, a, "병원\n예약\r\n")) == [m]
    assert _ids(_search(client, a, "병원\u3000예약")) == [m]  # 전각 공백


def test_around_other_family_message_is_invalid_message(client, family, other_family):
    a, _, _ = family
    _send(client, a, "우리 글")
    theirs = _send(client, other_family, "남의 비밀 글")
    r = _around(client, a, theirs)
    assert r.status_code == 400 and r.json()["code"] == "invalid_message"
    assert "남의" not in r.text


def test_around_even_limit_and_max_limit_sizes(client, family):
    a, _, group = family
    db = SessionLocal()
    uid = _uid(client, a)
    rows = [
        Message(group_id=group["id"], room_id=None, user_id=uid, text=f"m{i}") for i in range(250)
    ]
    db.add_all(rows)
    db.commit()
    ids = [m.id for m in rows]
    db.close()
    mid = ids[125]
    assert len(_around(client, a, mid, limit=10).json()) == 11  # 가운데 1 + 앞뒤 각 5
    assert len(_around(client, a, mid, limit=1).json()) == 1  # limit//2 == 0
    body = _around(client, a, mid, limit=200).json()
    assert len(body) == 201 and [m["id"] for m in body] == ids[25:226]
    assert _around(client, a, mid, limit=201).status_code == 422


def test_paging_with_room_id_has_no_overlap_or_gap(client, trio):
    a, b, _, _ = trio
    ab = _direct(client, a, _uid(client, b))
    sent = [_send(client, a if i % 2 else b, f"약속 {i}", ab) for i in range(7)]
    _send(client, a, "약속 가족방")
    seen, before = [], None
    while True:
        params = {"room_id": ab, "limit": 3}
        if before:
            params["before_id"] = before
        page = _search(client, a, "약속", **params).json()
        seen += [i["id"] for i in page["items"]]
        before = page["next_before_id"]
        if before is None:
            break
    assert seen == sorted(sent, reverse=True)
