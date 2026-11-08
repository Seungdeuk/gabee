"""평가용 요약 문장 내보내기 스크립트(evals/location/export_summaries.py) 시험. 가짜 데이터만 쓴다."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.features.location.models import LocationPlace, LocationPoint
from app.shared.config import settings
from app.shared.db import SessionLocal
from evals.location import export_summaries as ex

M = 1 / 111320.0
HOME = (37.0, 127.0)
KST = timedelta(hours=9)


def _ids(client, headers) -> tuple[str, str]:
    uid = client.get("/family-group/me", headers=headers).json()["id"]
    gid = client.get("/family-group/groups/me", headers=headers).json()["id"]
    return uid, gid


def _day_at_nine_kst(days_ago: int) -> tuple[str, datetime]:
    day = ((datetime.now(UTC) + KST) - timedelta(days=days_ago)).date()
    return day.isoformat(), datetime(day.year, day.month, day.day, 0, 0, tzinfo=UTC)  # KST 09:00


def _points(uid: str, gid: str, start_utc: datetime, minutes: int) -> None:
    with SessionLocal() as db:
        for k in range(minutes):
            wobble = ((k * 7) % 5 - 2) * 10 * M
            db.add(
                LocationPoint(
                    user_id=uid,
                    group_id=gid,
                    lat=HOME[0] + wobble,
                    lng=HOME[1] + wobble,
                    accuracy_m=10.0,
                    recorded_at=start_utc + timedelta(minutes=k),
                    received_at=start_utc,
                )
            )
        db.commit()


def _setup(client, family):
    _, b, _ = family
    uid, gid = _ids(client, b)
    with SessionLocal() as db:
        db.add(LocationPlace(user_id=uid, group_id=gid, name="원래집", lat=HOME[0], lng=HOME[1]))
        db.commit()
    return uid, gid


def test_export_has_no_coordinates_real_name_or_raw_place_name(client, family):
    uid, gid = _setup(client, family)
    day, nine = _day_at_nine_kst(2)
    _points(uid, gid, nine, 60)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = ex.find_user(db, uid)
        spans = ex.day_spans(db, user, datetime.fromisoformat(day).date(), now, {"원래집": "집"})
    assert [s["kind"] for s in spans] == ["stay"]  # 기록 없음은 뺀다
    assert spans[0]["place"] == "집"
    store = ex.build_store(None, {day: spans}, now)
    text = json.dumps(store, ensure_ascii=False)
    ex.check_clean(text, {"수진", uid, "원래집"})  # 가려야 할 값이 없다
    assert "나 |" in text and "집에서 머묾" in text
    assert "37." not in text and "127." not in text
    assert store["chunks"] and all(
        c["text"].startswith("나 |") for c in store["chunks"] if c["kind"] != "place"
    )


def test_old_days_survive_after_points_are_deleted_and_a_day_is_replaced(client, family):
    uid, gid = _setup(client, family)
    day, nine = _day_at_nine_kst(2)
    _points(uid, gid, nine, 60)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = ex.find_user(db, uid)
        spans = ex.day_spans(db, user, datetime.fromisoformat(day).date(), now, {})
    first = ex.build_store(None, {day: spans}, now)
    with SessionLocal() as db:  # 서버가 보관 기간이 지나 위치를 지운 상황
        db.execute(delete(LocationPoint).where(LocationPoint.user_id == uid))
        db.commit()
        assert (
            ex.day_spans(db, ex.find_user(db, uid), datetime.fromisoformat(day).date(), now, {})
            is None
        )
    again = ex.build_store(first, {}, now)
    assert again["days"] == first["days"] and again["chunks"] == first["chunks"]  # 파일에는 남는다
    replaced = ex.build_store(first, {day: []}, now)  # 같은 날을 다시 내보내면 그날만 바뀐다
    assert replaced["days"][day] == []


def test_unnamed_place_and_range_of_days(client, family):
    uid, gid = _setup(client, family)
    day, nine = _day_at_nine_kst(2)
    far = (nine, 30)
    _points(uid, gid, *far)  # 이름 붙인 곳(HOME)에 30분
    now = datetime.now(UTC)
    with SessionLocal() as db:
        days = ex.exportable_days(db, uid, now, settings.location_retention_days, False)
    today_kst = (now + KST).date()
    assert today_kst not in days and datetime.fromisoformat(day).date() in days
    with SessionLocal() as db:
        with_today = ex.exportable_days(db, uid, now, settings.location_retention_days, True)
    assert today_kst in with_today
    chunks = ex.chunks_from_days(
        {
            day: [
                {
                    "kind": "stay",
                    "start": f"{day}T09:00",
                    "end": f"{day}T10:00",
                    "place": None,
                    "origin": None,
                }
            ]
        }
    )
    assert any("이름 없는 곳에서 머묾" in c["text"] for c in chunks)


def test_helpers_reject_bad_input(tmp_path: Path):
    assert ex.parse_aliases(["집=홈", " 학원 = 공부방 "]) == {"집": "홈", "학원": "공부방"}
    with pytest.raises(ValueError):
        ex.parse_aliases(["집만"])
    with pytest.raises(ValueError):
        ex.check_clean("지민이 갔다", {"지민"})
    assert ex.inside_git_repo(Path(ex.__file__).parent)  # 저장소 안
    assert not ex.inside_git_repo(tmp_path)
