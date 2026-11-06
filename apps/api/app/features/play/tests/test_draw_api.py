"""가족 놀이터 이게 뭐게: 그림 올리기, 힌트, 정답 쓰기(10번), 점수, 끝내지 못한 채 닫힘, 이미지."""

from app.features.play.media import DRAW_MAX_BYTES
from app.features.play.tests.media_helpers import jpeg_bytes, png_bytes, size_of
from app.features.play.tests.test_quiz_api import BOARD, force_close, scores, trio

DRAWS = "/play/draws"


def make_draw(client, headers, answer="고양이", alt=("냥이",), hint2="야옹 하고 울어요", **extra):
    r = client.post(
        DRAWS,
        files={"file": ("d.png", png_bytes(), "image/png")},
        data={"answer": answer, "alt_answers": list(alt), "hint2": hint2, **extra},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def tries(client, headers, item_id, text):
    return client.post(f"/play/items/{item_id}/tries", json={"answer": text}, headers=headers)


def hint(client, headers, item_id):
    return client.post(f"/play/items/{item_id}/hints", headers=headers)


# ---------- 만들기 ----------
def test_create_draw_shows_everything_to_maker(client, family, play_data_dir):
    a, _, _ = family
    item = make_draw(client, a)
    assert item["game"] == 2 and item["is_maker"] and item["questions"] == []
    d = item["draw"]
    assert (d["answer"], d["alt_answers"], d["hint1"], d["hint2"]) == (
        "고양이",
        ["냥이"],
        "3글자",
        "야옹 하고 울어요",
    )
    assert item["image_url"] == f"/play/items/{item['id']}/image"
    files = list((play_data_dir / "play" / "drawings").rglob("*.png"))
    assert [f.stem for f in files] == [item["id"]]  # 파일 이름은 서버가 만든 id


def test_create_draw_validation(client, family, play_data_dir):
    a, _, _ = family
    post = lambda **kw: client.post(DRAWS, headers=a, **kw)  # noqa: E731
    ok_file = {"file": ("d.png", png_bytes(), "image/png")}
    assert post(files=ok_file, data={"answer": "  "}).status_code == 400
    assert post(files=ok_file, data={"answer": "가" * 41}).status_code == 400
    assert (
        post(files=ok_file, data={"answer": "고양이", "alt_answers": list("abcdef")}).status_code
        == 400
    )
    assert post(files=ok_file, data={"answer": "고양이", "hint2": "가" * 21}).status_code == 400
    jpeg = {"file": ("d.jpg", jpeg_bytes(), "image/jpeg")}
    assert (
        post(files=jpeg, data={"answer": "고양이"}).json()["code"] == "invalid_image"
    )  # 그림은 PNG 만
    fake = {"file": ("d.png", b"not an image", "image/png")}
    assert post(files=fake, data={"answer": "고양이"}).json()["code"] == "invalid_image"
    big = {"file": ("d.png", b"x" * (DRAW_MAX_BYTES + 10), "image/png")}
    assert post(files=big, data={"answer": "고양이"}).status_code == 413
    assert (
        post(files=ok_file, data={"answer": "고양이", "player_ids": ["없는사람"]}).status_code
        == 400
    )
    # 실패한 요청은 줄도 파일도 남기지 않는다
    assert not list(play_data_dir.rglob("*.png"))
    assert client.get(BOARD, headers=a).json()["sent"] == []


# ---------- 힌트와 점수 ----------
def test_hints_open_one_by_one_and_stop_at_two(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    seen = client.get(f"/play/items/{item['id']}", headers=b).json()["draw"]
    assert (seen["hint1"], seen["hint2"], seen["answer"], seen["hints_used"]) == (
        None,
        None,
        None,
        0,
    )
    d = hint(client, b, item["id"]).json()["draw"]
    assert (d["hint1"], d["hint2"], d["hints_used"]) == ("3글자", None, 1)
    d = hint(client, b, item["id"]).json()["draw"]
    assert (d["hint2"], d["hints_used"]) == ("야옹 하고 울어요", 2)
    r = hint(client, b, item["id"])
    assert r.status_code == 409 and r.json()["code"] == "no_more_hints"


def test_hint_alone_does_not_count_as_participating(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])
    board = client.get(BOARD, headers=b).json()
    assert [i["id"] for i in board["todo"]] == [item["id"]] and board["joined"] == []
    assert scores(item["id"]) == []


def test_correct_with_hint_scores_join_correct_minus_hint(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])
    r = tries(client, b, item["id"], "강아지")
    assert r.json()["draw"]["last_try_correct"] is False and not r.json()["draw"]["finished"]
    assert scores(item["id"]) == []  # 틀려도 감점도 점수도 없다
    out = tries(client, b, item["id"], " 고 양이 ").json()  # 공백을 무시한다
    assert out["draw"]["solved"] and out["draw"]["finished"] and out["my_state"] == "done"
    assert out["my_score"] == {"total": 25, "join": 10, "correct": 20, "hint": -5}
    assert scores(item["id"]) == [(1, 10), (2, 20), (5, -5)]
    assert out["draw"]["answer"] == "고양이"  # 끝낸 뒤에는 정답이 보인다
    assert [x["is_correct"] for x in out["my_answers"]] == [False, True]
    board = client.get(BOARD, headers=b).json()
    assert [i["id"] for i in board["joined"]] == [item["id"]]


def test_alt_answer_is_accepted_case_insensitive(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a, answer="Pizza", alt=("피자",))
    assert tries(client, b, item["id"], "PIZZA").json()["draw"]["solved"]
    item2 = make_draw(client, a, answer="Pizza", alt=("피자",))
    assert tries(client, b, item2["id"], "피자").json()["draw"]["solved"]


def test_ten_wrong_tries_end_with_join_points_only(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])
    for n in range(1, 10):
        d = tries(client, b, item["id"], f"틀림{n}").json()["draw"]
        assert d["tries_used"] == n and not d["finished"]
    out = tries(client, b, item["id"], "틀림10").json()
    assert out["draw"]["finished"] and not out["draw"]["solved"]
    assert out["my_score"] == {
        "total": 5,
        "join": 10,
        "correct": 0,
        "hint": -5,
    }  # 틀려도 힌트 감점은 한다(10 - 5)
    r = tries(client, b, item["id"], "고양이")
    assert r.status_code == 409 and r.json()["code"] == "already_finished"
    assert hint(client, b, item["id"]).status_code == 409


def test_two_hints_and_all_wrong_ends_at_zero(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])
    hint(client, b, item["id"])
    for n in range(10):
        out = tries(client, b, item["id"], f"틀림{n}").json()
    assert out["my_score"]["total"] == 0  # 참여 10 - 힌트 10
    assert scores(item["id"]) == [(1, 10), (5, -10)]


def test_closed_with_hint_and_a_try_gets_join_minus_hint(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])
    tries(client, b, item["id"], "강아지")  # 한 번 제출했으니 참여
    force_close(item["id"])
    client.get(BOARD, headers=b)
    assert scores(item["id"]) == [(1, 10), (3, 20), (5, -5)]


def test_hint_only_is_not_participating_even_when_closed(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    hint(client, b, item["id"])  # 답은 한 번도 안 냈다
    force_close(item["id"])
    board = client.get(BOARD, headers=b).json()
    assert board["past"] == [] and scores(item["id"]) == []  # 참여도 점수도 감점도 없다


def test_answers_endpoint_is_not_for_draw(client, family):
    a, b, _ = family
    item = make_draw(client, a)
    r = client.post(
        f"/play/items/{item['id']}/answers",
        json={"answers": [{"quiz_no": 0, "answer": "10"}]},
        headers=b,
    )
    assert r.status_code == 400 and r.json()["code"] == "use_tries"


def test_maker_and_outsiders_cannot_try(client, family, other_family):
    a, b, _ = family
    item = make_draw(client, a)
    assert tries(client, a, item["id"], "고양이").status_code == 403
    assert hint(client, a, item["id"]).status_code == 403
    assert tries(client, other_family, item["id"], "고양이").status_code == 404


# ---------- 마감 ----------
def test_all_finished_closes_and_pays_maker(client, family):
    a, b, _ = family
    item = make_draw(client, a)
    out = tries(client, b, item["id"], "고양이").json()
    assert out["closed"] is True  # 받는 사람이 모두 끝내 바로 닫힘
    mine = client.get(f"/play/items/{item['id']}", headers=a).json()
    assert (mine["maker_score_state"], mine["maker_score"]) == ("paid", 20)
    assert [fa["player"]["name"] for fa in mine["family_answers"]] == ["수진"]


def test_unfinished_tries_count_as_join_when_closed(client, family):
    a, b, _ = family
    c_headers = trio(client, family)[2]
    item = make_draw(client, a)
    tries(client, b, item["id"], "강아지")
    tries(client, b, item["id"], "토끼")  # 끝내지 못한 채 나감
    assert scores(item["id"]) == []
    assert (
        client.get(BOARD, headers=b).json()["joined"] == []
    )  # 맞히기 전엔 참여했어요로 안 옮겨진다
    force_close(item["id"])
    board = client.get(BOARD, headers=b).json()
    assert [i["id"] for i in board["past"]] == [item["id"]]  # 시도한 사람은 지난 결과에 남는다
    assert scores(item["id"]) == [(1, 10), (3, 20)]  # 시도한 사람 참여 +10, 낸 사람 +20
    client.get(BOARD, headers=b)
    client.get("/play/ranking", headers=b)
    assert scores(item["id"]) == [(1, 10), (3, 20)]  # 정산은 한 번만
    # 아무것도 안 한 영희는 지난 결과에 없다
    assert client.get(BOARD, headers=c_headers).json()["past"] == []
    r = tries(client, b, item["id"], "고양이")
    assert r.status_code == 409 and r.json()["code"] == "closed"


def test_draw_answer_hidden_from_unfinished_until_closed(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_draw(client, a)
    tries(client, b, item["id"], "강아지")
    d = client.get(f"/play/items/{item['id']}", headers=b).json()["draw"]
    assert d["answer"] is None and d["alt_answers"] is None
    force_close(item["id"])
    d = client.get(f"/play/items/{item['id']}", headers=b).json()["draw"]
    assert d["answer"] == "고양이"


# ---------- 이미지 ----------
def test_image_endpoint_permissions(client, family, other_family):
    a, b, _ = family
    item = make_draw(client, a)
    url = item["image_url"]
    r = client.get(url, headers=b)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert size_of(r.content) == (120, 90)
    assert "private" in r.headers["cache-control"]
    assert client.get(url, headers=other_family).status_code == 404
    assert client.get(url).status_code == 401
    assert client.get("/play/items/없는id/image", headers=a).status_code == 404
