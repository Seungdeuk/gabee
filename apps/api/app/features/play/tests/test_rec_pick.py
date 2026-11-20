"""가비 추천을 사용자마다 다르게 고르는 공통 함수: 후보 수의 절반 올림, 사용자·날짜별 고정."""

from datetime import date, timedelta

from app.features.play.rec_pick import pick_for_user, show_count

TODAY = date(2026, 11, 20)


def items(n):
    return [{"id": f"i{k}"} for k in range(n)]


def ids(picked):
    return [x["id"] for x in picked]


def test_show_count_is_half_rounded_up():
    assert [show_count(n) for n in range(0, 8)] == [0, 1, 1, 2, 2, 3, 3, 4]


def test_pick_keeps_original_order_and_count():
    source = items(5)
    picked = ids(pick_for_user(source, "g1", "u1", TODAY))
    assert len(picked) == 3
    assert picked == [i for i in ids(source) if i in picked]
    assert ids(source) == ["i0", "i1", "i2", "i3", "i4"]  # 입력은 바뀌지 않는다


def test_same_user_same_day_is_stable():
    first = ids(pick_for_user(items(7), "g1", "u1", TODAY))
    assert ids(pick_for_user(items(7), "g1", "u1", TODAY)) == first


def test_different_users_can_differ():
    picks = {tuple(ids(pick_for_user(items(7), "g1", f"u{k}", TODAY))) for k in range(20)}
    assert len(picks) > 1


def test_other_day_can_differ():
    picks = {
        tuple(ids(pick_for_user(items(7), "g1", "u1", TODAY + timedelta(days=d))))
        for d in range(30)
    }
    assert len(picks) > 1


def test_adding_an_item_keeps_most_of_the_pick():
    for k in range(10):
        before = set(ids(pick_for_user(items(3), "g1", f"u{k}", TODAY)))
        after = set(ids(pick_for_user(items(4), "g1", f"u{k}", TODAY)))
        assert before & after


def test_empty_and_single():
    assert pick_for_user([], "g1", "u1", TODAY) == []
    assert pick_for_user(items(1), "g1", "u1", TODAY) == items(1)
