"""가족 놀이터 골든벨: 만들기, 현황판, 답 보내기, 마감·정산, 순위."""

from datetime import UTC, datetime, timedelta

from app.features.play.models import PlayItem, PlayScore
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

QUIZ = "/play/quiz"
BOARD = "/play/board"


def quiz_body(n=3, **extra):
    qs = [
        {
            "qtype": 1,
            "question": "엄마 생신은 12월이다",
            "options": ["O", "X"],
            "answer_index": 1,
            "comment": "11월이야",
        },
        {
            "qtype": 2,
            "question": "아빠가 좋아하는 반찬은?",
            "options": ["계란말이", "멸치볶음", "김치찌개", "잡채"],
            "answer_index": 0,
        },
        {
            "qtype": 2,
            "question": "처음 간 여행지는?",
            "options": ["제주도", "강릉", "부산"],
            "answer_index": 0,
        },
    ]
    return {"questions": qs[:n], **extra}


def make_quiz(client, headers, n=3, **extra):
    r = client.post(QUIZ, json=quiz_body(n, **extra), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def answer(client, headers, item_id, bits):
    return client.post(
        f"/play/items/{item_id}/answers",
        json={"answers": [{"quiz_no": i + 1, "answer": b} for i, b in enumerate(bits)]},
        headers=headers,
    )


def trio(client, family):
    """지민(소유자)·수진에 영희를 더한 세 명 가족."""
    a, b, group = family
    c = signup(client, "영희")
    join_family(client, a, group["invite_code"], c)
    return a, b, c


def force_close(item_id):
    with SessionLocal() as db:
        item = db.get(PlayItem, item_id)
        item.close_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()


def scores(item_id):
    with SessionLocal() as db:
        return sorted(
            (s.reason, s.points) for s in db.query(PlayScore).filter(PlayScore.play_id == item_id)
        )


# ---------- 접근 ----------
def test_requires_login_and_family(client):
    assert client.get(BOARD).status_code == 401
    h = signup(client, "혼자")
    assert client.get(BOARD, headers=h).status_code == 400  # 가족 그룹이 먼저 필요


# ---------- 만들기 ----------
def test_create_quiz_stores_bits_and_hides_nothing_from_maker(client, family):
    a, _, _ = family
    item = make_quiz(client, a)
    assert item["game"] == 1 and item["is_maker"] and item["my_state"] == "maker"
    assert [q["answer"] for q in item["questions"]] == ["01", "1000", "100"]  # 정답은 비트 글자
    assert item["questions"][0]["comment"] == "11월이야"
    assert (item["progress_done"], item["progress_total"], item["closed"]) == (0, 1, False)
    assert item["maker_score_state"] == "pending"


def test_create_quiz_validation(client, family):
    a, _, _ = family
    bad_ox = quiz_body(1)
    bad_ox["questions"][0]["options"] = ["예", "아니오"]
    assert client.post(QUIZ, json=bad_ox, headers=a).status_code == 422
    over = quiz_body(1)
    over["questions"][0]["answer_index"] = 3
    assert client.post(QUIZ, json=over, headers=a).status_code == 422
    assert client.post(QUIZ, json={"questions": []}, headers=a).status_code == 422
    assert client.post(QUIZ, json=quiz_body(player_ids=["없는사람"]), headers=a).status_code == 400


def test_cannot_send_to_myself_or_alone(client, family):
    a, b, _ = family
    from sqlalchemy import select

    from app.features.family_group.models import User

    with SessionLocal() as db:
        a_id = db.scalar(select(User.id).where(User.name == "지민"))
    r = client.post(QUIZ, json=quiz_body(player_ids=[a_id]), headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_recipient"
    lone = signup(client, "외톨이")
    client.post("/family-group/groups", json={"name": "혼자 가족"}, headers=lone)
    r = client.post(QUIZ, json=quiz_body(), headers=lone)
    assert r.status_code == 400 and r.json()["code"] == "no_recipient"


# ---------- 현황판 ----------
def test_board_sections(client, family):
    a, b, _ = family
    item = make_quiz(client, a)
    mine = client.get(BOARD, headers=a).json()
    assert [i["id"] for i in mine["sent"]] == [item["id"]] and mine["todo"] == []
    theirs = client.get(BOARD, headers=b).json()
    assert [i["id"] for i in theirs["todo"]] == [item["id"]]
    assert theirs["todo"][0]["question_count"] == 3 and theirs["sent"] == []
    answer(client, b, item["id"], ["01", "1000", "100"])
    theirs = client.get(BOARD, headers=b).json()
    assert (
        theirs["todo"] == [] and theirs["joined"] == [] and len(theirs["past"]) == 1
    )  # 모두 답해 바로 닫힘
    assert len(client.get(BOARD, headers=a).json()["sent_past"]) == 1


def test_board_joined_while_waiting_for_others(client, family):
    a, b, _ = family
    _, _, c = trio(client, family)
    item = make_quiz(client, a)
    answer(client, b, item["id"], ["01", "1000", "100"])
    board = client.get(BOARD, headers=b).json()
    assert [i["id"] for i in board["joined"]] == [item["id"]]
    assert (board["joined"][0]["progress_done"], board["joined"][0]["progress_total"]) == (1, 2)
    assert [i["id"] for i in client.get(BOARD, headers=c).json()["todo"]] == [item["id"]]


# ---------- 답 보내기와 점수 ----------
def test_answer_scores_join_and_ratio(client, family):
    a, b, _ = family
    trio(client, family)  # 한 명 더 있어야 바로 닫히지 않는다
    item = make_quiz(client, a)
    r = answer(client, b, item["id"], ["01", "0100", "100"])  # 3문제 중 2개 맞힘
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["my_state"] == "done" and out["closed"] is False
    assert [x["is_correct"] for x in out["my_answers"]] == [True, False, True]
    assert out["my_score"] == {
        "total": 23,
        "join": 10,
        "correct": 13,
        "hint": 0,
    }  # 20 × 2/3 = 13.3 → 13
    assert scores(item["id"]) == [(1, 10), (2, 13)]
    assert [q["answer"] for q in out["questions"]] == [
        "01",
        "1000",
        "100",
    ]  # 푼 뒤에는 정답이 보인다


def test_all_wrong_still_gets_join_points(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_quiz(client, a, n=1)
    r = answer(client, b, item["id"], ["10"])
    assert r.json()["my_score"]["total"] == 10
    assert scores(item["id"]) == [(1, 10)]


def test_answers_hidden_before_answering(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_quiz(client, a)
    seen = client.get(f"/play/items/{item['id']}", headers=b).json()
    assert seen["my_state"] == "todo"
    assert all(q["answer"] is None and q["comment"] is None for q in seen["questions"])
    assert seen["my_answers"] is None and seen["family_answers"] is None


def test_answer_rules(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_quiz(client, a)
    iid = item["id"]
    r = answer(client, a, iid, ["01", "1000", "100"])
    assert r.status_code == 403 and r.json()["code"] == "maker_cannot_answer"
    assert (
        answer(client, b, iid, ["01", "1000"]).json()["code"] == "invalid_answers"
    )  # 문항이 모자람
    assert (
        answer(client, b, iid, ["01", "1100", "100"]).json()["code"] == "invalid_answers"
    )  # 보기를 둘 골랐음
    assert answer(client, b, iid, ["01", "1000", "100"]).status_code == 200
    again = answer(client, b, iid, ["10", "1000", "100"])
    assert again.status_code == 409 and again.json()["code"] == "already_answered"


def test_closed_item_rejects_answers(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_quiz(client, a)
    force_close(item["id"])
    r = answer(client, b, item["id"], ["01", "1000", "100"])
    assert r.status_code == 409 and r.json()["code"] == "closed"


def test_custom_recipients_only(client, family):
    a, b, _ = family
    _, _, c = trio(client, family)
    from sqlalchemy import select

    from app.features.family_group.models import User

    with SessionLocal() as db:
        b_id = db.scalar(select(User.id).where(User.name == "수진"))
    item = make_quiz(client, a, player_ids=[b_id])
    assert (item["progress_done"], item["progress_total"]) == (0, 1)
    assert client.get(f"/play/items/{item['id']}", headers=c).status_code == 404  # 받는 사람이 아님
    assert client.get(BOARD, headers=c).json()["todo"] == []
    assert answer(client, c, item["id"], ["01", "1000", "100"]).status_code == 403


# ---------- 마감과 정산 ----------
def test_everyone_answers_closes_and_pays_maker(client, family):
    a, b, _ = family
    item = make_quiz(client, a)
    r = answer(client, b, item["id"], ["01", "1000", "100"])
    assert r.json()["closed"] is True  # 받는 사람이 모두 답해 앞당겨 닫힘
    assert (4, 0) not in scores(item["id"])
    assert (3, 20) in scores(item["id"])  # 문제 낸 사람 +20
    made = client.get(f"/play/items/{item['id']}", headers=a).json()
    assert (made["maker_score"], made["maker_score_state"]) == (20, "paid")
    assert [f["player"]["name"] for f in made["family_answers"]] == [
        "수진"
    ]  # 닫힌 뒤에 가족 답이 보인다
    assert made["family_answers"][0]["answers"][0]["answer"] == "01"


def test_settle_is_idempotent(client, family):
    a, b, _ = family
    item = make_quiz(client, a)
    answer(client, b, item["id"], ["01", "1000", "100"])
    for _ in range(3):
        client.get(BOARD, headers=a)
        client.get(f"/play/items/{item['id']}", headers=b)
    assert scores(item["id"]).count((3, 20)) == 1


def test_nobody_answered_means_no_maker_points(client, family):
    a, _, _ = family
    item = make_quiz(client, a)
    force_close(item["id"])
    made = client.get(f"/play/items/{item['id']}", headers=a).json()
    assert (made["maker_score"], made["maker_score_state"]) == (0, "none_solved")
    assert made["family_answers"] == []
    assert scores(item["id"]) == []


def test_waits_for_everyone_until_closing_time(client, family):
    a, b, _ = family
    _, _, c = trio(client, family)
    item = make_quiz(client, a)
    answer(client, b, item["id"], ["01", "1000", "100"])
    assert client.get(f"/play/items/{item['id']}", headers=a).json()["closed"] is False
    assert (3, 20) not in scores(item["id"])  # 닫히기 전에는 점수가 없다
    force_close(item["id"])  # 24시간이 지남(영희는 안 풀었다)
    made = client.get(f"/play/items/{item['id']}", headers=a).json()
    assert made["maker_score_state"] == "paid" and (3, 20) in scores(item["id"])
    r = answer(client, c, item["id"], ["01", "1000", "100"])
    assert r.status_code == 409


def test_daily_limit_three_per_maker(client, family):
    a, b, _ = family
    ids = []
    for _ in range(4):
        item = make_quiz(client, a, n=1)
        answer(client, b, item["id"], ["01"])
        ids.append(item["id"])
    paid = [(3, 20) in scores(i) for i in ids]
    assert paid == [True, True, True, False]  # 낸 순서로 3건까지
    fourth = client.get(f"/play/items/{ids[3]}", headers=a).json()
    assert fourth["maker_score_state"] == "daily_limit"


# ---------- 순위 ----------
def test_ranking_sums_ledger(client, family):
    a, b, _ = family
    item = make_quiz(client, a)
    answer(client, b, item["id"], ["01", "1000", "100"])  # 수진 10 + 20
    rows = client.get("/play/ranking?period=week", headers=a).json()["rows"]
    by_name = {r["player"]["name"]: r for r in rows}
    assert by_name["수진"]["score"] == 30 and by_name["수진"]["by_game"]["1"] == 20
    assert by_name["수진"]["etc"] == 10 and by_name["수진"]["counts"]["1"] == 1
    assert by_name["수진"]["corrects"] == {"1": 3, "2": 0, "3": 0, "4": 0}  # 맞힌 문항 수
    assert by_name["지민"]["corrects"] == {"1": 0, "2": 0, "3": 0, "4": 0}
    assert by_name["지민"]["score"] == 20 and by_name["지민"]["etc"] == 20  # 문제 내기 +20
    assert [r["player"]["name"] for r in rows][0] == "수진"
    assert client.get("/play/ranking?period=all", headers=a).status_code == 200
    assert client.get("/play/ranking?period=year", headers=a).status_code == 422


def test_quota_counts_todays_items(client, family):
    a, b, _ = family
    assert client.get("/play/quota", headers=a).json() == {"limit": 3, "used": 0, "left": 3}
    make_quiz(client, a)
    make_quiz(client, a)
    assert client.get("/play/quota", headers=a).json() == {"limit": 3, "used": 2, "left": 1}
    assert client.get("/play/quota", headers=b).json()["used"] == 0  # 사람마다 센다
    for _ in range(3):
        make_quiz(client, a)
    assert client.get("/play/quota", headers=a).json() == {"limit": 3, "used": 5, "left": 0}
    assert client.get("/play/quota").status_code == 401


def test_other_family_cannot_see(client, family, other_family):
    a, _, _ = family
    item = make_quiz(client, a)
    r = client.get(f"/play/items/{item['id']}", headers=other_family)
    assert r.status_code == 404  # 다른 가족의 문제는 있는지조차 알려 주지 않는다
