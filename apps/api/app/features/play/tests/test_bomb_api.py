"""가족 놀이터 문장 폭탄방: 방 열기·입장, 게임 시작, 이어 말하기·판정, 시간 초과, 탈락·우승·점수, 관전 응원 쿨타임."""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.play import bomb, service
from app.features.play import bomb_vote as vote
from app.features.play.models import PlayItem, PlayScore
from app.features.play.tests.test_quiz_api import trio
from app.shared.db import SessionLocal

BASE = "/play/bomb"
T0 = datetime(2026, 11, 6, 3, 0, 0, tzinfo=UTC)


_CLOCK = None


@pytest.fixture
def clock(monkeypatch):
    """게임 시간을 손으로 움직인다. clock.at(초) 로 처음 시각 + 초에 맞춘다."""

    class Clock:
        now = T0

        def at(self, sec: float) -> None:
            self.now = T0 + timedelta(seconds=sec)

    c = Clock()
    global _CLOCK
    _CLOCK = c
    monkeypatch.setattr(bomb, "_now", lambda: c.now)
    monkeypatch.setattr(service, "_now", lambda: c.now)  # 현황판의 열린 방 계산도 같은 시계를 쓴다
    bomb.reset_cheers()
    vote.reset()
    return c


def open_room(client, headers):
    r = client.post(BASE, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def join(client, headers, room_id):
    if _CLOCK is not None:
        _CLOCK.now += timedelta(milliseconds=1)  # 들어온 순서가 시각으로 구분되게 한다
    r = client.post(f"{BASE}/{room_id}/join", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def start(client, headers, room_id, life=2, sec=10):
    r = client.post(f"{BASE}/{room_id}/start", json={"life": life, "sec": sec}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def say(client, headers, room_id, word):
    return client.post(f"{BASE}/{room_id}/say", json={"word": word}, headers=headers)


def state(client, headers, room_id):
    r = client.get(f"{BASE}/{room_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def scores(room_id):
    with SessionLocal() as db:
        return sorted(
            (s.reason, s.points, s.round_no)
            for s in db.query(PlayScore).filter(PlayScore.play_id == room_id)
        )


def two_room(client, family, clock, life=2, sec=10):
    """지민(방장)과 수진이 들어온 방을 만들고 시작한다."""
    a, b, _ = family
    room = open_room(client, a)
    join(client, b, room["id"])
    return a, b, room["id"], start(client, a, room["id"], life, sec)


# ---------- 방 ----------
def test_room_lifecycle_and_lobby(client, family, clock):
    a, b, _ = family
    assert client.get(BASE + "/current", headers=a).json() is None
    room = open_room(client, a)
    assert room["phase"] == "lobby" and room["is_host"] and room["my_status"] == "player"
    assert [(p["name"], p["joined"], p["host"]) for p in room["players"]] == [
        ("지민", True, True),
        ("수진", False, False),  # 아직 안 들어온 가족
    ]
    assert (room["life"], room["sec"]) == (3, 10)  # 로비에서는 기본값
    cur = client.get(BASE + "/current", headers=b).json()
    assert cur["id"] == room["id"] and cur["my_status"] == "none" and not cur["is_host"]
    r = client.post(BASE, headers=b)
    assert r.status_code == 409 and r.json()["code"] == "room_open"  # 가족마다 방은 하나
    joined = join(client, b, room["id"])
    assert joined["my_status"] == "player"
    assert [p["name"] for p in joined["players"] if p["joined"]] == ["지민", "수진"]
    assert join(client, b, room["id"])["my_status"] == "player"  # 다시 들어와도 그대로


def test_cannot_open_alone(client):
    from tests.helpers import signup

    lone = signup(client, "혼자")
    client.post("/family-group/groups", json={"name": "혼자 가족"}, headers=lone)
    r = client.post(BASE, headers=lone)
    assert r.status_code == 400 and r.json()["code"] == "no_recipient"


def test_room_is_private_to_family(client, family, other_family, clock):
    a, _, _ = family
    room = open_room(client, a)
    assert client.get(f"{BASE}/{room['id']}", headers=other_family).status_code == 404
    assert client.post(f"{BASE}/{room['id']}/join", headers=other_family).status_code == 404
    assert client.get(BASE + "/current", headers=other_family).json() is None


def test_lobby_expires_after_an_hour_and_new_room_can_open(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    clock.at(3601)
    assert state(client, a, room["id"])["phase"] == "closed"
    assert client.post(f"{BASE}/{room['id']}/join", headers=b).json()["code"] == "closed"
    assert client.post(BASE, headers=b).status_code == 201  # 닫힌 방이 있어도 새로 열 수 있다


def test_only_host_starts_and_needs_two(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    r = client.post(f"{BASE}/{room['id']}/start", json={"life": 3, "sec": 10}, headers=a)
    assert r.status_code == 409 and r.json()["code"] == "need_players"
    join(client, b, room["id"])
    r = client.post(f"{BASE}/{room['id']}/start", json={"life": 3, "sec": 10}, headers=b)
    assert r.status_code == 403 and r.json()["code"] == "not_host"
    for bad in (
        {"life": 0, "sec": 10},
        {"life": 6, "sec": 10},
        {"life": 3, "sec": 0},
        {"life": 3, "sec": 61},
    ):
        assert client.post(f"{BASE}/{room['id']}/start", json=bad, headers=a).status_code == 422
    out = start(client, a, room["id"], life=5, sec=60)
    assert out["phase"] == "playing" and (out["life"], out["sec"], out["round_no"]) == (5, 60, 1)
    r = client.post(f"{BASE}/{room['id']}/start", json={"life": 3, "sec": 10}, headers=a)
    assert r.status_code == 409 and r.json()["code"] == "in_game"


def test_host_cannot_close_during_game(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock)
    r = client.post(f"{BASE}/{room_id}/close", headers=a)
    assert r.status_code == 409 and r.json()["code"] == "in_game"


def test_lobby_close_and_guest_cannot_close(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    join(client, b, room["id"])
    assert client.post(f"{BASE}/{room['id']}/close", headers=b).status_code == 403
    assert client.post(f"{BASE}/{room['id']}/close", headers=a).json()["phase"] == "closed"
    assert client.get(BASE + "/current", headers=a).json() is None


def test_guest_can_leave_lobby_but_host_cannot(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    join(client, b, room["id"])
    out = client.post(f"{BASE}/{room['id']}/leave", headers=b).json()
    assert out["my_status"] == "none" and [p["name"] for p in out["players"] if p["joined"]] == [
        "지민"
    ]
    r = client.post(f"{BASE}/{room['id']}/leave", headers=a)
    assert r.status_code == 409 and r.json()["code"] == "host_cannot_leave"


# ---------- 게임 진행 ----------
def test_turn_order_host_first_then_join_order(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, c, room["id"])  # 영희가 먼저 들어오고
    join(client, b, room["id"])  # 수진이 나중에
    out = start(client, a, room["id"])
    assert [p["name"] for p in out["players"] if p["joined"]] == ["지민", "영희", "수진"]
    assert out["turn"]["player"]["name"] == "지민"  # 방장이 첫 차례
    assert out["turn"]["seconds_left"] == 10
    assert say(client, a, room["id"], "누가").status_code == 200
    assert state(client, a, room["id"])["turn"]["player"]["name"] == "영희"
    assert say(client, c, room["id"], "어제").status_code == 200
    assert state(client, a, room["id"])["turn"]["player"]["name"] == "수진"


def test_say_rules(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock)
    r = say(client, b, room_id, "누가")
    assert r.status_code == 409 and r.json()["code"] == "not_your_turn"
    assert say(client, a, room_id, "").status_code == 422
    assert say(client, a, room_id, "가" * 11).status_code == 422  # 10자까지
    out = say(client, a, room_id, "  누가   어제 ").json()  # 공백은 정리된다
    assert out["messages"][-1]["text"] == "누가 어제" and out["chain"] == 1
    assert out["turn"]["player"]["name"] == "수진"
    assert say(client, a, room_id, "또").json()["code"] == "not_your_turn"


def test_ending_sentence_costs_a_life_and_restarts_sentence(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=2)
    say(client, a, room_id, "엄마가")  # 지민
    say(client, b, room_id, "시장에서")  # 수진
    say(client, a, room_id, "사과를")
    out = say(client, b, room_id, "샀다").json()  # 문장을 끝냈다 → 수진 생명 -1
    last = out["messages"][-1]
    assert last["ended"] and last["lost_life"] and not last["out"]
    lives = {p["name"]: p["lives"] for p in out["players"] if p["joined"]}
    assert lives == {"지민": 2, "수진": 1}
    assert out["chain"] == 0  # 문장을 새로 시작
    assert out["turn"]["player"]["name"] == "지민"
    # 새 문장은 앞 말과 이어 판정하지 않는다: 한 단어 "누가"는 끝이 아니다
    assert not say(client, a, room_id, "누가").json()["messages"][-1]["ended"]


def test_repeating_a_word_costs_a_life(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=3)
    say(client, a, room_id, "밥을")  # 지민
    out = say(client, b, room_id, "밥을").json()  # 수진이 바로 앞 말을 또 했다
    last = out["messages"][-1]
    assert last["ended"] and last["reason"] == "repeat" and last["lost_life"]
    assert {p["name"]: p["lives"] for p in out["players"] if p["joined"]} == {"지민": 3, "수진": 2}
    assert out["chain"] == 0 and out["turn"]["player"]["name"] == "지민"  # 문장을 새로 시작
    # 새 문장에서는 같은 말을 다시 써도 된다
    assert not say(client, a, room_id, "밥을").json()["messages"][-1]["ended"]


def test_repeating_an_older_word_in_the_same_sentence_also_costs_a_life(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=3)
    say(client, a, room_id, "나는")
    say(client, b, room_id, "어제")
    say(client, a, room_id, "학교에서")
    out = say(client, b, room_id, "나는").json()  # 앞에서 나온 말을 또 했다
    assert out["messages"][-1]["reason"] == "repeat" and out["messages"][-1]["lost_life"]


def test_repeated_answer_in_one_word_costs_a_life(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=3)
    out = say(client, a, room_id, "네네").json()
    assert out["messages"][-1]["reason"] == "repeat" and out["messages"][-1]["ended"]


def test_normal_end_has_end_reason(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=3)
    say(client, a, room_id, "엄마가")
    out = say(client, b, room_id, "일어났다").json()
    assert out["messages"][-1]["reason"] == "end"
    assert out["messages"][0]["reason"] is None


def test_elimination_ends_round_winner_and_scores(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=1)
    say(client, a, room_id, "엄마가")
    out = say(client, b, room_id, "일어났다").json()  # 수진이 문장을 끝냄 → 생명 1개라 탈락
    assert out["phase"] == "finished" and out["my_status"] == "player"
    assert out["turn"] is None
    res = out["result"]
    assert res["winner"]["name"] == "지민" and res["round_no"] == 1
    assert [(r["player"]["name"], r["rank"], r["points"]) for r in res["ranking"]] == [
        ("지민", 1, 50),  # 방장: 참여 점수 없이 문제 내기 20 + 우승 30
        ("수진", 2, 10),
    ]
    assert res["ranking"][1]["sub"] == "1번째로 탈락"
    assert res["longest_len"] == 1 and res["is_record"] and res["prev_record"] is None
    assert res["my_points"] == 10  # 진 사람(수진)이 본 것
    assert state(client, a, room_id)["result"]["my_points"] == 50  # 이긴 사람(방장 지민)이 본 것
    assert scores(room_id) == [
        (1, 0, 1),
        (1, 10, 1),
        (3, 20, 1),
        (4, 30, 1),
    ]  # 방장 참여 0점 줄, 수진 참여 10, 방장 문제 내기 20, 우승 30
    # 같은 판은 다시 정산하지 않는다
    state(client, a, room_id)
    state(client, b, room_id)
    assert len(scores(room_id)) == 4
    # 이긴 사람의 순위 점수: 우승 30, 참여 10
    ranking = client.get("/play/ranking?period=all", headers=a).json()["rows"]
    by_name = {r["player"]["name"]: r for r in ranking}
    assert by_name["지민"]["by_game"]["4"] == 30 and by_name["지민"]["corrects"]["4"] == 1
    assert by_name["지민"]["counts"]["4"] == 1 and by_name["수진"]["counts"]["4"] == 1


def test_timeout_costs_a_life_lazily(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=2, sec=10)
    clock.at(5)
    assert state(client, a, room_id)["turn"]["seconds_left"] == 5
    clock.at(10.5)  # 지민이 10초 안에 말하지 못했다
    out = state(client, b, room_id)
    first = out["messages"][0]
    assert first["kind"] == "timeout" and first["player"]["name"] == "지민" and first["lost_life"]
    assert {p["name"]: p["lives"] for p in out["players"] if p["joined"]} == {"지민": 1, "수진": 2}
    assert out["turn"]["player"]["name"] == "수진"
    # 수진의 시간은 지민이 시간 초과된 순간(10초)부터, 한 차례 지났으니 제한이 9.5초로 줄었다
    assert out["turn"]["limit"] == 9.5
    assert out["turn"]["seconds_left"] == pytest.approx(9.0, abs=0.01)


def test_turn_limit_shrinks_each_turn_down_to_the_floor():
    assert bomb.turn_limit(10, 0) == 10
    assert bomb.turn_limit(10, 1) == 9.5
    assert bomb.turn_limit(10, 2) == 9.03
    assert bomb.turn_limit(10, 200) == 3  # 아무리 지나도 3초 밑으로는 안 내려간다
    assert bomb.turn_limit(60, 1) == 57
    assert (
        bomb.turn_limit(2, 0) == 2 and bomb.turn_limit(2, 50) == 2
    )  # 방에서 정한 시간이 3초보다 짧으면 그대로
    assert bomb.turn_limit(1, 9) == 1


def test_first_turn_of_a_new_round_resets_the_speed(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=1, sec=10)
    assert state(client, a, room_id)["turn"]["limit"] == 10
    clock.at(10.5)  # 지민 시간 초과로 한 판이 끝난다
    assert state(client, b, room_id)["phase"] == "finished"
    out = start(client, a, room_id, life=1, sec=10)  # 한 판 더
    assert out["turn"]["limit"] == 10 and out["turn"]["seconds_left"] == 10


def test_nobody_polling_still_fills_all_missed_turns(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=1, sec=10)
    clock.at(25)  # 지민 시간 초과(탈락) → 한 명만 남아 판이 끝난다
    out = state(client, a, room_id)
    assert out["phase"] == "finished" and out["result"]["winner"]["name"] == "수진"
    assert [m["kind"] for m in out["messages"]] == ["timeout"]
    assert scores(room_id) == [(1, 0, 1), (1, 10, 1), (3, 20, 1), (4, 30, 1)]


def test_say_after_timeout_is_rejected_and_timeout_is_kept(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=2, sec=10)
    clock.at(11)
    r = say(client, a, room_id, "누가")  # 이미 시간이 지났다
    assert r.status_code == 409 and r.json()["code"] == "not_your_turn"
    out = state(client, a, room_id)
    assert out["messages"][0]["kind"] == "timeout"


def test_three_players_game_to_the_last_one(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, b, room["id"])
    join(client, c, room["id"])
    rid = room["id"]
    start(client, a, rid, life=1, sec=10)
    say(client, a, rid, "엄마가")
    out = say(client, b, rid, "일어났다").json()  # 수진 탈락 → 영희 차례
    assert out["phase"] == "playing"
    me = {p["name"]: p for p in out["players"] if p["joined"]}
    assert me["수진"]["out"] and not me["지민"]["out"]
    assert out["turn"]["player"]["name"] == "영희"
    assert state(client, b, rid)["my_status"] == "out"
    out = say(client, c, rid, "밥을 먹었다").json()  # 영희도 탈락 → 지민 우승
    assert out["phase"] == "finished" and out["result"]["winner"]["name"] == "지민"
    assert [r["player"]["name"] for r in out["result"]["ranking"]] == ["지민", "영희", "수진"]
    assert [r["sub"] for r in out["result"]["ranking"]][1:] == ["2번째로 탈락", "1번째로 탈락"]


def test_late_joiner_watches_and_next_round_includes_them(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, b, room["id"])
    rid = room["id"]
    start(client, a, rid, life=3, sec=10)
    clock.at(1)
    out = join(client, c, rid)  # 게임 중에 들어옴 → 이번 판은 구경
    assert out["my_status"] == "spectator"
    assert next(p for p in out["players"] if p["name"] == "영희")["spectator"]
    r = say(client, c, rid, "끼어들기")
    assert r.status_code == 409 and r.json()["code"] == "not_your_turn"
    # 판을 끝내고(수진이 시간 초과 3번) 한 판 더: 영희도 참여
    for sec in (12, 22, 32):
        clock.at(sec)
        say(client, a, rid, "그리고")
        state(client, b, rid)
    s = state(client, a, rid)
    # 한 판 더를 눌러 다시 시작
    if s["phase"] == "finished":
        out = start(client, a, rid, life=2, sec=10)
        assert out["round_no"] == 2
        assert {p["name"] for p in out["players"] if p["joined"] and not p["spectator"]} == {
            "지민",
            "수진",
            "영희",
        }


def test_leaving_during_game_eliminates_and_may_end_it(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=3)
    clock.at(2)
    out = client.post(f"{BASE}/{room_id}/leave", headers=b).json()
    assert out["my_status"] == "none"
    assert out["phase"] == "finished" and out["result"]["winner"]["name"] == "지민"
    assert scores(room_id) == [(1, 0, 1), (1, 10, 1), (3, 20, 1), (4, 30, 1)]


def test_play_again_and_family_record(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=1)
    for first, second in (
        ("엄마가", "어제"),
        ("시장에서", "사과를"),
    ):  # 같은 말을 반복하면 생명이 줄어서 서로 다른 말을 잇는다
        say(client, a, room_id, first)
        say(client, b, room_id, second)
    out = say(client, a, room_id, "먹었다").json()  # 지민이 끝냄 → 수진 우승, 이어가기 4개
    assert out["result"]["winner"]["name"] == "수진" and out["result"]["longest_len"] == 4
    assert out["result"]["is_record"] and out["result"]["prev_record"] is None
    out = start(client, a, room_id, life=1, sec=10)  # 한 판 더
    assert out["round_no"] == 2 and out["phase"] == "playing" and out["messages"] == []
    say(client, a, room_id, "비가")
    out = say(client, b, room_id, "왔다").json()
    assert out["result"]["round_no"] == 2 and out["result"]["longest_len"] == 1
    assert (
        not out["result"]["is_record"] and out["result"]["prev_record"] == 4
    )  # 우리 가족 신기록은 그대로
    # 1판: 참여 2줄(방장 0점) + 방장 문제 내기 + 우승, 2판: 참여 2줄(방장 0점) + 우승. 방장의 문제 내기 20은 방마다 한 번
    assert scores(room_id) == [
        (1, 0, 1),
        (1, 0, 2),
        (1, 10, 1),
        (1, 10, 2),
        (3, 20, 1),
        (4, 30, 1),
        (4, 30, 2),
    ]


def test_game_cap_two_hours_ends_without_winner(client, family, clock):
    a, b, room_id, _ = two_room(client, family, clock, life=5, sec=60)
    clock.at(60 * 60 * 2 + 5)
    out = state(client, a, room_id)
    assert out["phase"] == "finished" or out["phase"] == "closed"
    assert out["result"]["winner"] is None
    assert [s[0] for s in scores(room_id)] == [1, 1, 3]  # 우승 점수 없이 참여 둘과 방장 문제 내기만


# ---------- 관전 응원 ----------
def test_cheer_only_when_out_or_watching_with_cooldown(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, b, room["id"])
    join(client, c, room["id"])
    rid = room["id"]
    start(client, a, rid, life=1, sec=10)
    r = client.post(f"{BASE}/{rid}/cheer", json={"text": "힘내요"}, headers=a)
    assert r.status_code == 403 and r.json()["code"] == "still_playing"  # 게임 중인 사람은 못 한다
    say(client, a, rid, "엄마가")
    say(client, b, rid, "일어났다")  # 수진 탈락
    out = state(client, b, rid)
    assert out["my_status"] == "out" and out["cheers"] == ["힘내요", "아슬아슬", "끝내지 마!"]
    r = client.post(f"{BASE}/{rid}/cheer", json={"text": "힘내요"}, headers=b)
    assert r.status_code == 200
    cheer_msgs = [m for m in r.json()["messages"] if m["kind"] == "cheer"]
    assert [(m["player"]["name"], m["text"]) for m in cheer_msgs] == [("수진", "힘내요")]
    assert r.json()["cheer_wait"] == 5
    # 난타 방지: 5초 안에 또 보내면 막힌다
    clock.at(2)
    r = client.post(f"{BASE}/{rid}/cheer", json={"text": "아슬아슬"}, headers=b)
    assert r.status_code == 429 and r.json()["code"] == "cheer_cooldown"
    assert r.headers["retry-after"] == "3"
    assert state(client, b, rid)["cheer_wait"] == pytest.approx(3, abs=0.01)
    assert len([m for m in state(client, a, rid)["messages"] if m["kind"] == "cheer"]) == 1
    clock.at(5.1)
    assert (
        client.post(f"{BASE}/{rid}/cheer", json={"text": "아슬아슬"}, headers=b).status_code == 200
    )
    # 영희는 아직 게임 중이라 응원할 수 없다
    r = client.post(f"{BASE}/{rid}/cheer", json={"text": "끝내지 마!"}, headers=c)
    assert r.status_code == 403 and r.json()["code"] == "still_playing"


def test_cheer_validation_and_per_person_cooldown(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, b, room["id"])
    rid = room["id"]
    start(client, a, rid, life=2, sec=10)
    join(client, c, rid)  # 게임 중에 들어와 구경하는 영희
    r = client.post(f"{BASE}/{rid}/cheer", json={"text": "아무 말이나"}, headers=c)
    assert r.status_code == 400 and r.json()["code"] == "invalid_cheer"  # 정해진 말만
    assert client.post(f"{BASE}/{rid}/cheer", json={"text": "힘내요"}, headers=c).status_code == 200
    assert client.post(f"{BASE}/{rid}/cheer", json={"text": "힘내요"}, headers=c).status_code == 429
    out = client.get(f"{BASE}/{rid}", headers=a).json()
    assert [m["text"] for m in out["messages"] if m["kind"] == "cheer"] == ["힘내요"]


def test_cheers_are_dropped_when_the_round_ends(client, family, clock):
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, b, room["id"])
    join(client, c, room["id"])
    rid = room["id"]
    start(client, a, rid, life=1, sec=10)
    say(client, a, rid, "엄마가")
    say(client, b, rid, "일어났다")  # 수진 탈락
    assert client.post(f"{BASE}/{rid}/cheer", json={"text": "힘내요"}, headers=b).status_code == 200
    assert len([m for m in state(client, a, rid)["messages"] if m["kind"] == "cheer"]) == 1
    out = say(client, c, rid, "밥을 먹었다").json()  # 판이 끝난다
    assert out["phase"] == "finished"
    assert [m for m in out["messages"] if m["kind"] == "cheer"] == []  # 응원은 버려졌다
    assert out["cheer_wait"] == 0


def test_cheer_needs_a_running_game_and_room(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    r = client.post(f"{BASE}/{room['id']}/cheer", json={"text": "힘내요"}, headers=b)
    assert r.status_code == 409 and r.json()["code"] == "not_playing"


# ---------- 현황판 ----------
def test_open_room_shows_on_board(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    board_b = client.get("/play/board", headers=b).json()
    assert [(i["id"], i["game"]) for i in board_b["todo"]][:1] == [
        (room["id"], 4)
    ]  # 받는 쪽은 맨 위
    assert client.get("/play/board", headers=a).json()["sent"][0]["id"] == room["id"]
    assert client.get("/play/board", headers=a).json()["todo"] == []
    client.post(f"{BASE}/{room['id']}/close", headers=a)
    assert client.get("/play/board", headers=b).json()["todo"] == []


def test_room_model_row(client, family, clock):
    a, _, _ = family
    room = open_room(client, a)
    with SessionLocal() as db:
        item = db.get(PlayItem, room["id"])
        assert item.game == 4 and item.player_ids == []


def test_started_bomb_room_counts_in_daily_make_quota(client, family, clock):
    a, b, _ = family
    room = open_room(client, a)
    assert (
        client.get("/play/quota", headers=a).json()["used"] == 0
    )  # 판을 시작하기 전에는 세지 않는다
    join(client, b, room["id"])
    start(client, a, room["id"])
    assert client.get("/play/quota", headers=a).json() == {"limit": 3, "used": 1, "left": 2}
    assert client.get("/play/quota", headers=b).json()["used"] == 0  # 방장만 센다


# ---------- 판정 투표 ----------
def vote_start(client, headers, room_id, kind):
    return client.post(f"{BASE}/{room_id}/vote/start", json={"kind": kind}, headers=headers)


def cast(client, headers, room_id, yes):
    return client.post(f"{BASE}/{room_id}/vote", json={"yes": yes}, headers=headers)


def three_room(client, family, clock, life=2, sec=10):
    """지민(방장)·영희·수진 순서로 들어와 시작한 세 명 방. 차례는 지민 → 영희 → 수진. (지민, 영희, 수진, 방 id)를 돌려준다."""
    a, b, c = trio(client, family)
    room = open_room(client, a)
    join(client, c, room["id"])
    join(client, b, room["id"])
    start(client, a, room["id"], life, sec)
    return a, c, b, room["id"]


def three_words(client, a, c, b, room_id):
    """지민·영희·수진이 차례로 말한다(문장은 안 끝남). 수진의 "사과를"이 방금 말이고 다음 차례는 지민."""
    for who, word in ((a, "엄마가"), (c, "시장에서"), (b, "사과를")):
        assert say(client, who, room_id, word).status_code == 200


def lives(out):
    return {p["name"]: p["lives"] for p in out["players"] if p["joined"]}


def test_call_vote_pass_makes_the_last_word_an_ending(client, family, clock):
    a, c, b, rid = three_room(client, family, clock)
    three_words(client, a, c, b, rid)
    out = state(client, a, rid)
    assert out["can_call"] and not out["can_unfair"] and out["call_msg_id"] == "t3"
    assert not state(client, b, rid)["can_call"]  # 자기 말에는 신청 못 한다
    clock.at(3)
    out = vote_start(client, a, rid, "call").json()
    v = out["vote"]
    assert (v["kind"], v["word"], v["yes"], v["no"], v["waiting"]) == ("call", "사과를", 1, 0, 2)
    assert v["my_choice"] == "yes" and not v["can_vote"]  # 신청한 사람은 자동 찬성
    assert not out["can_call"]
    # 투표 중에는 게임 시계가 멈춰 있고(남은 시간이 투표가 시작된 순간 그대로) 이어 말할 수 없다
    limit = bomb.turn_limit(10, 3)
    clock.at(8)
    mid = state(client, c, rid)
    assert mid["turn"]["seconds_left"] == pytest.approx(limit - 3, abs=0.05)
    assert mid["vote"]["can_vote"] is True
    assert say(client, a, rid, "그리고").json()["code"] == "vote_open"
    out = cast(client, c, rid, True).json()  # 영희 찬성
    assert out["vote"]["yes"] == 2 and out["vote"]["can_vote"] is False
    out = cast(client, b, rid, False).json()  # 수진 반대: 모두 골랐으니 바로 결과, 찬성 2 > 반대 1
    assert out["vote"] is None
    assert out["messages"][-1]["kind"] == "vote"
    assert out["messages"][-1]["text"] == "투표 통과, 끝난 말로 바뀌었어요"
    last_word = next(m for m in out["messages"] if m["id"] == "t3")
    assert last_word["ended"] and last_word["lost_life"]
    assert lives(out) == {"지민": 2, "영희": 2, "수진": 1}
    assert out["chain"] == 0  # 문장이 새로 시작된다
    assert out["turn"]["player"]["name"] == "지민"
    assert out["turn"]["seconds_left"] == pytest.approx(limit - 3, abs=0.05)  # 멈춘 시간은 빠졌다


def test_call_vote_needs_two_yes_and_more_than_no(client, family, clock):
    a, c, b, rid = three_room(client, family, clock)
    three_words(client, a, c, b, rid)
    vote_start(client, a, rid, "call")
    clock.at(11)  # 아무도 안 골라 기권: 찬성 1(신청한 사람뿐)이라 기각
    out = state(client, c, rid)
    assert out["vote"] is None
    assert out["messages"][-1]["text"] == "투표 기각, 판정은 그대로예요"
    assert lives(out) == {"지민": 2, "영희": 2, "수진": 2}
    assert not state(client, a, rid)["can_call"]  # 같은 사람은 이번 판에 어라?를 이미 썼다
    assert vote_start(client, a, rid, "call").json()["code"] == "vote_used"


def test_call_vote_rules_and_tie(client, family, clock):
    a, c, b, rid = three_room(client, family, clock)
    three_words(client, a, c, b, rid)
    assert vote_start(client, b, rid, "call").json()["code"] == "cannot_call"  # 내 말
    assert (
        vote_start(client, a, rid, "unfair").json()["code"] == "cannot_call"
    )  # 내가 탈락한 게 아니다
    assert vote_start(client, a, rid, "nope").status_code == 422
    assert cast(client, a, rid, True).json()["code"] == "no_vote"
    vote_start(client, a, rid, "call")
    assert vote_start(client, c, rid, "call").json()["code"] == "vote_open"  # 한 번에 투표는 하나
    cast(client, b, rid, False)
    assert cast(client, b, rid, True).json()["code"] == "already_voted"
    assert cast(client, a, rid, True).json()["code"] == "already_voted"  # 신청한 사람은 이미 찬성
    out = cast(client, c, rid, False).json()  # 찬성 1 : 반대 2
    assert out["messages"][-1]["text"] == "투표 기각, 판정은 그대로예요"


def test_unfair_vote_restores_life_and_continues(client, family, clock):
    a, c, b, rid = three_room(client, family, clock, life=1)
    three_words(client, a, c, b, rid)
    out = say(
        client, a, rid, "샀다"
    ).json()  # 지민이 문장을 끝내 탈락(생명 1개)했다. 둘이 남아 판은 계속
    assert out["my_status"] == "out" and out["can_unfair"] and out["call_msg_id"] == "t4"
    assert not state(client, c, rid)["can_unfair"]
    assert vote_start(client, c, rid, "unfair").json()["code"] == "cannot_call"
    out = vote_start(client, a, rid, "unfair").json()
    assert (out["vote"]["kind"], out["vote"]["yes"], out["vote"]["waiting"]) == ("unfair", 0, 2)
    assert (
        cast(client, a, rid, True).json()["code"] == "cannot_vote"
    )  # 탈락한 본인은 투표하지 않는다
    cast(client, c, rid, True)
    out = cast(client, b, rid, True).json()  # 찬성 2
    assert out["vote"] is None
    assert out["messages"][-1]["text"] == "투표 통과, 다시 게임에 돌아와요"
    assert out["my_status"] == "player" and lives(out)["지민"] == 1
    assert next(m for m in out["messages"] if m["id"] == "t4")["ended"] is False
    assert out["chain"] == 4  # 문장은 끊기지 않고 이어진다
    assert out["turn"]["player"]["name"] == "영희"
    assert vote_start(client, a, rid, "unfair").json()["code"] == "vote_used"


def test_unfair_vote_still_available_after_others_keep_playing(client, family, clock):
    a, c, b, rid = three_room(client, family, clock, life=1)
    three_words(client, a, c, b, rid)
    say(client, a, rid, "샀다")  # 지민 탈락
    assert say(client, c, rid, "누가").status_code == 200  # 영희가 바로 이어 말해도
    assert say(client, b, rid, "어제").status_code == 200  # 수진까지 말해도
    out = state(client, a, rid)
    assert out["can_unfair"] and out["my_status"] == "out"
    out = vote_start(client, a, rid, "unfair").json()
    assert out["vote"]["word"] == "샀다" and out["vote"]["kind"] == "unfair"
    before = out["turn"]["seconds_left"]
    clock.at(5)  # 투표 중에는 지민을 뺀 둘 중 지금 차례 사람의 시계가 멈춰 있다
    assert state(client, c, rid)["turn"]["seconds_left"] == pytest.approx(before, abs=0.01)
    cast(client, c, rid, True)
    out = cast(client, b, rid, True).json()
    assert out["messages"][-1]["text"] == "투표 통과, 다시 게임에 돌아와요"
    assert out["my_status"] == "player" and lives(out)["지민"] == 1
    assert out["chain"] == 6  # 문장이 이어졌으니 엄마가·시장에서·사과를·샀다·누가·어제


def test_unfair_vote_when_only_a_life_was_lost(client, family, clock):
    a, c, b, rid = three_room(client, family, clock, life=2)
    for who, word in ((a, "엄마가"), (c, "시장에서"), (b, "사과를")):
        say(client, who, rid, word)
    out = say(client, a, rid, "샀다").json()  # 지민이 문장을 끝내 생명 -1(탈락은 아님)
    assert lives(out)["지민"] == 1 and out["my_status"] == "player"
    assert out["can_unfair"] and not state(client, c, rid)["can_unfair"]
    out = vote_start(client, a, rid, "unfair").json()
    assert out["vote"]["waiting"] == 2 and not out["vote"]["can_vote"]  # 본인은 투표하지 않는다
    assert cast(client, a, rid, True).json()["code"] == "cannot_vote"
    cast(client, c, rid, True)
    out = cast(client, b, rid, True).json()
    assert out["messages"][-1]["text"] == "투표 통과, 생명이 돌아와요"
    assert lives(out)["지민"] == 2
    assert next(m for m in out["messages"] if m["id"] == "t4")["ended"] is False
    assert not out["can_unfair"]  # 한 판에 한 번


def test_unfair_vote_not_available_after_speaking_again(client, family, clock):
    a, c, b, rid = three_room(client, family, clock, life=3)
    three_words(client, a, c, b, rid)
    say(client, a, rid, "샀다")  # 지민 생명 -1
    say(client, c, rid, "누가")
    say(client, b, rid, "어제")
    out = say(client, a, rid, "학교에서").json()  # 지민이 새 문장을 또 말했다
    assert not out["can_unfair"]
    assert vote_start(client, a, rid, "unfair").json()["code"] == "cannot_call"


def test_unfair_vote_not_offered_when_it_ends_the_round(client, family, clock):
    a, b, rid, _ = two_room(client, family, clock, life=1)
    for who, word in ((a, "엄마가"), (b, "시장에서"), (a, "사과를")):
        say(client, who, rid, word)
    out = say(client, b, rid, "샀다").json()  # 수진이 탈락해 한 명만 남아 판이 끝난다
    assert out["phase"] == "finished" and not out["can_unfair"]
    assert vote_start(client, b, rid, "unfair").json()["code"] == "not_playing"


def test_call_vote_pass_can_eliminate_and_finish_the_round(client, family, clock):
    a, c, b, rid = three_room(client, family, clock, life=1)
    three_words(client, a, c, b, rid)
    say(client, a, rid, "샀다")  # 지민 탈락, 영희·수진이 남는다
    assert say(client, c, rid, "누가").status_code == 200
    assert (
        vote_start(client, a, rid, "call").json()["code"] == "cannot_call"
    )  # 탈락한 사람은 어라?를 못 한다
    out = vote_start(client, b, rid, "call").json()  # 수진이 영희의 말에 어라?
    assert out["vote"]["waiting"] == 1  # 살아있는 둘뿐이라 영희만 고르면 된다
    out = cast(
        client, c, rid, True
    ).json()  # 찬성 2: 영희 말이 끝난 말로 바뀌어 생명 0, 수진만 남는다
    assert out["phase"] == "finished" and out["result"]["winner"]["name"] == "수진"
    assert out["vote"] is None and not out["can_call"]


def test_vote_end_gives_at_least_three_seconds(client, family, clock):
    a, c, b, rid = three_room(client, family, clock)
    three_words(client, a, c, b, rid)
    clock.at(8)  # 지민 차례에 0.57초 남았을 때 어라?
    assert state(client, a, rid)["turn"]["seconds_left"] < 1
    vote_start(client, a, rid, "call")
    clock.at(18)  # 투표 마감(기각): 남은 시간이 0.57초였지만 이어질 때는 3초
    out = state(client, a, rid)
    assert out["vote"] is None and out["phase"] == "playing"
    assert out["turn"]["seconds_left"] == pytest.approx(3.0, abs=0.05)
    clock.at(20)
    out = state(client, a, rid)
    assert out["turn"]["seconds_left"] == pytest.approx(1.0, abs=0.05) and lives(out)["지민"] == 2
    clock.at(21.5)  # 3초를 쓰고도 말하지 않으면 그때 시간 초과
    out = state(client, a, rid)
    assert lives(out)["지민"] == 1


def test_vote_clock_pauses_and_resumes(client, family, clock):
    a, c, b, rid = three_room(client, family, clock)
    three_words(client, a, c, b, rid)
    clock.at(2)
    before = state(client, a, rid)["turn"]["seconds_left"]
    vote_start(client, a, rid, "call")
    clock.at(9)  # 투표 중 7초가 흘렀지만 게임 시간은 그대로
    assert state(client, a, rid)["turn"]["seconds_left"] == pytest.approx(before, abs=0.01)
    clock.at(13)  # 투표는 12초에 마감돼 기각, 멈춘 10초를 뺀 시계가 이어진다
    out = state(client, a, rid)
    assert out["vote"] is None and out["phase"] == "playing"
    assert out["turn"]["seconds_left"] == pytest.approx(before - 1, abs=0.05)
