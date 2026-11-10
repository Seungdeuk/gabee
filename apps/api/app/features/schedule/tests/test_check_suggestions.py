"""데일리 체크 추천 문구: 읽기 API(무작위·제외·비활성·빈 목록)와 시드 스크립트(검사·멱등)."""

from pathlib import Path

import pytest

from app.shared.db import SessionLocal

from ..constants import SUGGEST_CHEER, SUGGEST_HABIT
from ..models import CheckSuggestion


def _put(*rows: CheckSuggestion) -> None:
    with SessionLocal() as db:
        db.add_all(rows)
        db.commit()


def _habit(content, kind=1, goal=None, unit=None, active=True) -> CheckSuggestion:
    return CheckSuggestion(
        category=SUGGEST_HABIT, content=content, kind=kind, goal=goal, unit=unit, active=active
    )


def _cheer(content, active=True) -> CheckSuggestion:
    return CheckSuggestion(category=SUGGEST_CHEER, content=content, active=active)


# ---------------------------------------------------------------- 읽기 API
def test_habit_suggestions_default_three_with_fields(client, family):
    a, _b, _g = family
    _put(
        _habit("약 먹기"),
        _habit("물 마시기", 2, 8, "잔"),
        _habit("산책하기"),
        _habit("스트레칭"),
        _habit("일기 쓰기"),
    )
    r = client.get("/schedule/check/suggestions/habits", headers=a)
    assert r.status_code == 200, r.text
    got = r.json()
    assert len(got) == 3
    assert len({g["name"] for g in got}) == 3
    water = {"name": "물 마시기", "kind": 2, "goal": 8, "unit": "잔"}
    for g in got:
        assert g == water or g == {"name": g["name"], "kind": 1, "goal": None, "unit": None}


def test_habit_suggestions_exclude_inactive_and_limit(client, family):
    a, _b, _g = family
    _put(_habit("약 먹기"), _habit("산책하기"), _habit("꺼둔 습관", active=False))
    r = client.get(
        "/schedule/check/suggestions/habits",
        params={"exclude": ["약 먹기"], "limit": 5},
        headers=a,
    )
    assert [g["name"] for g in r.json()] == [
        "산책하기"
    ]  # 제외한 것·비활성은 빠지고, 모자라면 있는 만큼만


def test_habit_suggestions_do_not_mix_cheers(client, family):
    a, _b, _g = family
    _put(_cheer("정말 잘하셨어요"))
    assert client.get("/schedule/check/suggestions/habits", headers=a).json() == []


def test_cheer_suggestions_default_two(client, family):
    a, _b, _g = family
    _put(
        _cheer("정말 잘하셨어요"),
        _cheer("보고 싶어요"),
        _cheer("자랑스러워요"),
        _cheer("끈 문구", active=False),
    )
    r = client.get("/schedule/check/suggestions/cheers", headers=a)
    assert r.status_code == 200, r.text
    got = [g["message"] for g in r.json()]
    assert len(got) == 2 and len(set(got)) == 2
    assert "끈 문구" not in got
    assert set(got) <= {"정말 잘하셨어요", "보고 싶어요", "자랑스러워요"}


def test_suggestions_empty_table_returns_empty_list(client, family):
    a, _b, _g = family
    assert client.get("/schedule/check/suggestions/habits", headers=a).json() == []
    assert client.get("/schedule/check/suggestions/cheers", headers=a).json() == []


def test_suggestions_need_login(client):
    assert client.get("/schedule/check/suggestions/habits").status_code in (401, 403)
    assert client.get("/schedule/check/suggestions/cheers").status_code in (401, 403)


def test_suggestions_pick_varies(client, family):
    """무작위인지: 후보 20개에서 3개씩 여러 번 받으면 같은 조합만 나오지 않는다."""
    a, _b, _g = family
    _put(*[_habit(f"습관{i}") for i in range(20)])
    seen = {
        tuple(
            sorted(
                g["name"]
                for g in client.get("/schedule/check/suggestions/habits", headers=a).json()
            )
        )
        for _ in range(8)
    }
    assert len(seen) > 1


def test_unique_category_content(client):
    from sqlalchemy.exc import IntegrityError

    _put(_cheer("보고 싶어요"))
    _put(_habit("보고 싶어요"))  # 다른 category 는 같은 글이어도 된다
    with pytest.raises(IntegrityError):
        _put(_cheer("보고 싶어요"))


# ---------------------------------------------------------------- 시드 스크립트
def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_seed_files_in_repo_are_valid():
    """저장소에 있는 시드 파일 두 개가 형식·길이·중복 검사를 통과한다."""
    from scripts.seed_check_suggestions import parse_cheers, parse_habits

    habits, habit_errors = parse_habits()
    cheers, cheer_errors = parse_cheers()
    assert habit_errors == [] and cheer_errors == []
    assert len(habits) > 100 and len(cheers) > 300


def test_parse_habits_rules(tmp_path):
    from scripts.seed_check_suggestions import parse_habits

    ok = _write(tmp_path, "ok.txt", "# 주석\n\n약 먹기|체크||\n물 마시기|횟수|8|잔\n")
    rows, errors = parse_habits(ok)
    assert errors == []
    assert [(r.content, r.kind, r.goal, r.unit) for r in rows] == [
        ("약 먹기", 1, None, None),
        ("물 마시기", 2, 8, "잔"),
    ]
    bad = _write(
        tmp_path,
        "bad.txt",
        "약 먹기|체크|3|\n걷기|횟수|1|번\n물|횟수|8|\n가나다|방식|\n약 먹기|체크||\n약 먹기|체크||\n"
        + "가" * 21
        + "|체크||\n",
    )
    _rows, errors = parse_habits(bad)
    assert len(errors) == 6


def test_parse_cheers_rules(tmp_path):
    from scripts.seed_check_suggestions import parse_cheers

    rows, errors = parse_cheers(
        _write(tmp_path, "c.txt", "# 주석\n잘하셨어요\n잘하셨어요\n" + "가" * 51 + "\n")
    )
    assert [r.content for r in rows] == ["잘하셨어요"]
    assert len(errors) == 2


def test_seed_insert_is_idempotent(client):
    from scripts.seed_check_suggestions import Row, insert_missing

    rows = [Row(SUGGEST_HABIT, "약 먹기", 1), Row(SUGGEST_CHEER, "잘하셨어요")]
    with SessionLocal() as db:
        assert insert_missing(db, rows) == 2
    with SessionLocal() as db:
        assert insert_missing(db, rows + [Row(SUGGEST_CHEER, "보고 싶어요")]) == 1
        assert db.query(CheckSuggestion).count() == 3
