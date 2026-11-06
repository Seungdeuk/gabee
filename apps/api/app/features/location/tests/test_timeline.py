"""위치 점 → 구간 변환기(timeline.convert) 시험. 순수 계산이라 DB 없이 돈다."""

from datetime import datetime, timedelta

from app.features.location import timeline as tl

BASE = datetime(2026, 11, 9, 8, 0)
HOME = (37.0, 127.0)
SCHOOL = (37.016, 127.0)  # 집에서 북쪽으로 약 1.8km
M = 1 / 111320.0  # 1m 가 위도 몇 도인지


def _at(minute: int) -> datetime:
    return BASE + timedelta(minutes=minute)


def _stay(place, start, end, wobble=30):
    """place 둘레 wobble(m) 안에서 1분마다 점을 찍는다(결정적 잔떨림)."""
    return [
        tl.Pt(
            _at(m),
            place[0] + ((m * 7) % 5 - 2) * wobble / 2 * M,
            place[1] + ((m * 3) % 5 - 2) * wobble / 2 * M,
            10.0,
        )
        for m in range(start, end)
    ]


def _walk(a, b, start, end):
    n = end - start
    return [
        tl.Pt(
            _at(start + k),
            a[0] + (b[0] - a[0]) * (k + 0.5) / n,
            a[1] + (b[1] - a[1]) * (k + 0.5) / n,
            10.0,
        )
        for k in range(n)
    ]


PLACES = [tl.KnownPlace("home", "집", *HOME), tl.KnownPlace("school", "학교", *SCHOOL)]


def test_stay_move_stay_with_names_and_accurate_boundaries():
    pts = _stay(HOME, 0, 60) + _walk(HOME, SCHOOL, 60, 90) + _stay(SCHOOL, 90, 200)
    segs = tl.convert(pts, PLACES)
    assert [(s.kind, s.place) for s in segs] == [("stay", "집"), ("move", "학교"), ("stay", "학교")]
    assert segs[1].origin == "집"
    assert abs(segs[0].end - _at(60)) <= timedelta(minutes=4)  # 떠나는 길의 점은 머묾에서 빠진다
    assert abs(segs[2].start - _at(90)) <= timedelta(minutes=4)
    assert segs[0].start == _at(0) and segs[2].end == _at(199)


def test_short_stop_is_not_a_stay():
    pts = _stay(HOME, 0, 30) + _stay((37.004, 127.0), 30, 36) + _stay(HOME, 36, 80)  # 6분 멈춤
    segs = tl.convert(pts, PLACES)
    assert all(s.kind != "stay" or s.place == "집" for s in segs)
    assert not any(s.kind == "stay" and s.place is None for s in segs)


def test_gap_longer_than_five_minutes_is_no_record_and_never_filled():
    pts = _stay(HOME, 0, 40) + _stay(HOME, 70, 120)  # 30분 비어 있다(같은 장소)
    segs = tl.convert(pts, PLACES)
    assert [s.kind for s in segs] == ["stay", "no_record", "stay"]
    gap = segs[1]
    assert gap.start == _at(39) and gap.end == _at(70)  # 빈 시간을 앞 위치로 이어 붙이지 않는다


def test_small_gap_keeps_one_stay():
    pts = _stay(HOME, 0, 20) + _stay(HOME, 24, 60)  # 4분 비어도 한 번의 머묾
    segs = tl.convert(pts, PLACES)
    assert [s.kind for s in segs] == ["stay"]


def test_window_fills_leading_and_trailing_blank_time():
    pts = _stay(HOME, 30, 90)
    segs = tl.convert(pts, PLACES, window=(_at(0), _at(180)))
    assert [(s.kind, s.start, s.end) for s in segs] == [
        ("no_record", _at(0), _at(30)),
        ("stay", _at(30), _at(89)),
        ("no_record", _at(89), _at(180)),
    ]
    assert tl.convert([], PLACES, window=(_at(0), _at(60))) == [
        tl.Seg("no_record", _at(0), _at(60))
    ]


def test_inaccurate_points_are_dropped():
    pts = _stay(HOME, 0, 60)
    wild = [tl.Pt(_at(20), 37.05, 127.05, 500.0)]  # 정확도 500m: 버린다
    segs = tl.convert(pts + wild, PLACES)
    assert [s.kind for s in segs] == ["stay"]


def test_unnamed_place_has_no_name_and_outside_zone_is_anomaly():
    far = (37.033, 127.033)
    pts = _stay(HOME, 0, 60) + _walk(HOME, far, 60, 90) + _stay(far, 90, 150)
    inside = tl.convert(pts, PLACES)
    assert [(s.kind, s.place) for s in inside if s.kind in ("stay", "anomaly")] == [
        ("stay", "집"),
        ("stay", None),
    ]
    zone = tl.ZoneRef(HOME[0], HOME[1], 500.0)
    outside = tl.convert(pts, PLACES, zone)
    assert [s.kind for s in outside if s.kind in ("stay", "anomaly")] == ["stay", "anomaly"]


def test_user_named_place_is_never_an_anomaly():
    zone = tl.ZoneRef(HOME[0], HOME[1], 300.0)
    segs = tl.convert(_stay(SCHOOL, 0, 60), PLACES, zone)  # 구역 밖이지만 이름 붙인 곳
    assert [(s.kind, s.place) for s in segs] == [("stay", "학교")]


def test_frequent_unnamed_places_become_candidates_with_stable_id():
    cafe = (37.008, 127.016)
    pts = []
    for day in range(4):
        base = day * 400
        pts += [
            tl.Pt(p.t + timedelta(minutes=base), p.lat, p.lng, p.accuracy_m)
            for p in _stay(cafe, 0, 30)
        ]
        pts += [
            tl.Pt(p.t + timedelta(minutes=base), p.lat, p.lng, p.accuracy_m)
            for p in _stay(HOME, 100, 160)
        ]
    segs = tl.convert(pts, [tl.KnownPlace("home", "집", *HOME)])
    found = tl.frequent_unnamed(segs)
    assert len(found) == 1 and found[0].visits == 4
    assert (
        found[0].id
        == tl.candidate_id(found[0].lat, found[0].lng)
        == tl.frequent_unnamed(segs)[0].id
    )
    assert tl.frequent_unnamed(segs, min_visits=5) == []


def test_empty_and_single_point_inputs():
    assert tl.convert([]) == []
    assert tl.convert([tl.Pt(_at(0), *HOME, 5.0)]) == []  # 점 하나는 구간이 되지 못한다
