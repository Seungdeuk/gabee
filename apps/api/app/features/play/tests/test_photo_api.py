"""가족 놀이터 찰칵! 탐정단: 사진 올리기, 줄여 보기, 선택식 답, 점수, 풀이 중 사진은 확대 조각만."""

from app.features.play.tests.media_helpers import jpeg_bytes, png_bytes, size_of
from app.features.play.tests.test_quiz_api import force_close, scores, trio

PHOTOS = "/play/photos"
OPTIONS = ["식탁", "소파", "창문", "책상"]


def make_photo(client, headers, **over):
    data = {
        "source": 2,
        "zoom": 8,
        "box_x": 0.5,
        "box_y": 0.5,
        "question": "이건 어디일까요?",
        "options": OPTIONS,
        "answer_index": 1,
        "comment": "거실이에요",
        **over,
    }
    r = client.post(
        PHOTOS, files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")}, data=data, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def pick(client, headers, item_id, bits):
    return client.post(
        f"/play/items/{item_id}/answers",
        json={"answers": [{"quiz_no": 0, "answer": bits}]},
        headers=headers,
    )


def shrink(client, headers, item_id):
    return client.post(f"/play/items/{item_id}/hints", headers=headers)


def test_create_photo_maker_sees_answer_and_full_image(client, family, play_data_dir):
    a, _, _ = family
    item = make_photo(client, a)
    p = item["photo"]
    assert (p["answer"], p["comment"], p["zoom"], p["options"]) == (
        "0100",
        "거실이에요",
        8,
        OPTIONS,
    )
    assert [f.stem for f in (play_data_dir / "play" / "photos").rglob("*.jpg")] == [item["id"]]
    r = client.get(item["image_url"], headers=a)
    assert r.headers["content-type"] == "image/jpeg" and size_of(r.content) == (800, 600)


def test_create_photo_accepts_png_and_validates(client, family, play_data_dir):
    a, _, _ = family
    ok = {"file": ("p.png", png_bytes((300, 200)), "image/png")}
    base = {
        "source": 1,
        "zoom": 4,
        "box_x": 0.2,
        "box_y": 0.8,
        "question": "무엇?",
        "options": ["가", "나"],
        "answer_index": 0,
    }
    assert client.post(PHOTOS, files=ok, data=base, headers=a).status_code == 201
    post = lambda **over: client.post(  # noqa: E731
        PHOTOS,
        files={"file": ("p.png", png_bytes((300, 200)), "image/png")},
        data={**base, **over},
        headers=a,
    )
    assert post(zoom=5).status_code == 400
    assert post(source=3).status_code == 400
    assert post(box_x=1.5).status_code == 422
    assert post(options=["가"]).status_code == 400
    assert post(options=["가", "가"]).status_code == 400
    assert post(answer_index=3).status_code == 400
    assert post(question="가" * 21).status_code == 400
    assert post(comment="가" * 101).status_code == 400
    bad = client.post(
        PHOTOS, files={"file": ("p.jpg", b"nope", "image/jpeg")}, data=base, headers=a
    )
    assert bad.json()["code"] == "invalid_image"
    assert len(list((play_data_dir / "play" / "photos").rglob("*.jpg"))) == 1  # 처음 성공한 한 건만


def test_solver_gets_zoomed_crop_not_original(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_photo(client, a)
    seen = client.get(f"/play/items/{item['id']}", headers=b).json()
    assert seen["photo"]["answer"] is None and seen["photo"]["comment"] is None
    assert seen["photo"]["zoom"] == 8 and seen["photo"]["shrinks_used"] == 0
    assert (
        seen["photo"]["box_x"] is None and seen["photo"]["box_y"] is None
    )  # 풀이 중에는 위치를 알리지 않는다
    crop = client.get(seen["image_url"], headers=b)
    assert size_of(crop.content) == (100, 75)  # 8배 확대 = 800×600 의 1/8
    # 줄여 보기를 할 때마다 배율이 절반이 되고 사진 주소도 달라진다
    one = shrink(client, b, item["id"]).json()
    assert (one["photo"]["zoom"], one["photo"]["shrinks_used"]) == (4, 1)
    assert one["image_url"] != seen["image_url"]
    assert size_of(client.get(one["image_url"], headers=b).content) == (200, 150)
    two = shrink(client, b, item["id"]).json()
    assert two["photo"]["zoom"] == 2
    r = shrink(client, b, item["id"])
    assert r.status_code == 409 and r.json()["code"] == "no_more_hints"


def test_correct_answer_scores_and_reveals_full_photo(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_photo(client, a)
    shrink(client, b, item["id"])
    out = pick(client, b, item["id"], "0100").json()
    assert out["my_state"] == "done"
    assert out["my_score"] == {"total": 25, "join": 10, "correct": 20, "hint": -5}
    assert scores(item["id"]) == [(1, 10), (2, 20), (5, -5)]
    assert out["photo"]["answer"] == "0100" and out["photo"]["zoom"] == 8  # 푼 뒤에는 원본 배율로
    assert (out["photo"]["box_x"], out["photo"]["box_y"]) == (0.5, 0.5)
    assert size_of(client.get(out["image_url"], headers=b).content) == (800, 600)
    r = pick(client, b, item["id"], "1000")
    assert r.status_code == 409 and r.json()["code"] == "already_answered"
    assert shrink(client, b, item["id"]).status_code == 409


def test_wrong_answer_with_shrink_loses_hint_points(client, family):
    a, b, _ = family
    trio(client, family)
    item = make_photo(client, a)
    shrink(client, b, item["id"])
    out = pick(client, b, item["id"], "1000").json()
    assert out["my_score"]["total"] == 5 and out["my_answers"][0]["is_correct"] is False
    assert scores(item["id"]) == [(1, 10), (5, -5)]  # 틀려도 줄여 보기 감점은 한다


def test_answer_validation_and_roles(client, family, other_family):
    a, b, _ = family
    trio(client, family)
    item = make_photo(client, a)
    iid = item["id"]
    assert pick(client, b, iid, "0110").json()["code"] == "invalid_answers"  # 둘을 골랐다
    assert pick(client, b, iid, "01").json()["code"] == "invalid_answers"  # 보기 수와 다르다
    wrong_no = client.post(
        f"/play/items/{iid}/answers",
        json={"answers": [{"quiz_no": 1, "answer": "0100"}]},
        headers=b,
    )
    assert wrong_no.json()["code"] == "invalid_answers"
    assert pick(client, a, iid, "0100").status_code == 403  # 낸 사람은 풀 수 없다
    assert pick(client, other_family, iid, "0100").status_code == 404
    assert client.get(item["image_url"], headers=other_family).status_code == 404


def test_closed_photo_shows_full_image_and_family_answers(client, family):
    a, b, _ = family
    c = trio(client, family)[2]
    item = make_photo(client, a)
    pick(client, b, item["id"], "0100")
    force_close(item["id"])
    seen = client.get(f"/play/items/{item['id']}", headers=c).json()  # 풀지 않은 영희도 결과를 본다
    assert seen["closed"] and seen["photo"]["answer"] == "0100"
    assert [fa["player"]["name"] for fa in seen["family_answers"]] == ["수진"]
    assert size_of(client.get(seen["image_url"], headers=c).content) == (800, 600)
    assert pick(client, c, item["id"], "0100").json()["code"] == "closed"
    mine = client.get(f"/play/items/{item['id']}", headers=a).json()
    assert (mine["maker_score_state"], mine["maker_score"]) == ("paid", 20)
