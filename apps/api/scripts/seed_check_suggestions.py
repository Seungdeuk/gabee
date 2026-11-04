"""데일리 체크 추천 문구(events_check_suggestions)를 txt 에서 DB 로 넣는다.

    cd apps/api
    python -m scripts.seed_check_suggestions            # 검사만 한다(DB 에 쓰지 않음, 읽기만)
    python -m scripts.seed_check_suggestions --apply    # 없는 문구만 넣는다

- 읽는 파일: scripts/seed_data/check_habits.txt(추천 습관), scripts/seed_data/check_cheers.txt(응원 문구). 다른 txt 는 참고용이라 읽지 않는다.
- '#' 으로 시작하는 줄과 빈 줄은 건너뛴다. 습관은 `이름|방식|목표|단위`(방식은 체크 또는 횟수), 응원은 한 줄에 문구 하나.
- 형식·길이·중복을 먼저 모두 검사하고, 하나라도 틀리면 아무것도 넣지 않고 끝낸다.
- 여러 번 실행해도 안전하다: (category, content) 가 이미 있으면 건너뛰고, 기존 행은 고치지 않는다.
- 어느 DB 에 쓰는지(호스트)를 출력한다. --apply 없이는 쓰지 않으므로 먼저 검사해 본다.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.features.schedule.constants import (
    CHECK_GOAL_MAX,
    CHECK_KIND_CHECK,
    CHECK_KIND_COUNT,
    SUGGEST_CHEER,
    SUGGEST_HABIT,
)
from app.features.schedule.models import CheckSuggestion
from app.shared.config import settings
from app.shared.db import SessionLocal

DATA_DIR = Path(__file__).parent / "seed_data"
HABITS_FILE = DATA_DIR / "check_habits.txt"
CHEERS_FILE = DATA_DIR / "check_cheers.txt"

HABIT_NAME_MAX = 20  # 앱 습관 이름 상한(서버 열은 60)
UNIT_MAX = 10
CHEER_MAX = 50  # 앱 응원 문구 상한(서버 열은 60)
KIND_BY_LABEL = {"체크": CHECK_KIND_CHECK, "횟수": CHECK_KIND_COUNT}


@dataclass(frozen=True)
class Row:
    category: int
    content: str
    kind: int | None = None
    goal: int | None = None
    unit: str | None = None


def _lines(path: Path):
    """(줄 번호, 내용) — 주석·빈 줄은 뺀다."""
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield no, line


def parse_habits(path: Path = HABITS_FILE) -> tuple[list[Row], list[str]]:
    """추천 습관 파일을 읽어 (행 목록, 오류 목록)을 돌려준다."""
    rows: list[Row] = []
    errors: list[str] = []
    seen: set[str] = set()
    for no, line in _lines(path):
        where = f"{path.name}:{no}"
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            errors.append(f"{where} 칸이 4개가 아니에요(이름|방식|목표|단위): {line}")
            continue
        name, label, goal_s, unit = parts
        if not name or len(name) > HABIT_NAME_MAX:
            errors.append(f"{where} 이름은 1~{HABIT_NAME_MAX}자예요: {name!r}")
            continue
        if name in seen:
            errors.append(f"{where} 이름이 중복이에요: {name}")
            continue
        kind = KIND_BY_LABEL.get(label)
        if kind is None:
            errors.append(f"{where} 방식은 체크 또는 횟수예요: {label!r}")
            continue
        if kind == CHECK_KIND_CHECK:
            if goal_s or unit:
                errors.append(f"{where} 체크는 목표·단위를 비워요: {line}")
                continue
            rows.append(Row(SUGGEST_HABIT, name, kind))
        else:
            if not goal_s.isdigit() or not 2 <= int(goal_s) <= CHECK_GOAL_MAX:
                errors.append(f"{where} 횟수의 목표는 2~{CHECK_GOAL_MAX} 숫자예요: {goal_s!r}")
                continue
            if not unit or len(unit) > UNIT_MAX:
                errors.append(f"{where} 횟수의 단위는 1~{UNIT_MAX}자예요: {unit!r}")
                continue
            rows.append(Row(SUGGEST_HABIT, name, kind, int(goal_s), unit))
        seen.add(name)
    return rows, errors


def parse_cheers(path: Path = CHEERS_FILE) -> tuple[list[Row], list[str]]:
    """응원 문구 파일을 읽어 (행 목록, 오류 목록)을 돌려준다."""
    rows: list[Row] = []
    errors: list[str] = []
    seen: set[str] = set()
    for no, line in _lines(path):
        where = f"{path.name}:{no}"
        if len(line) > CHEER_MAX:
            errors.append(f"{where} {CHEER_MAX}자를 넘어요({len(line)}자): {line}")
        elif line in seen:
            errors.append(f"{where} 문구가 중복이에요: {line}")
        else:
            seen.add(line)
            rows.append(Row(SUGGEST_CHEER, line))
    return rows, errors


def insert_missing(db, rows: list[Row]) -> int:
    """(category, content) 가 아직 없는 행만 넣고 넣은 수를 돌려준다. 기존 행은 건드리지 않는다."""
    existing = set(db.execute(select(CheckSuggestion.category, CheckSuggestion.content)).all())
    added = 0
    for r in rows:
        if (r.category, r.content) in existing:
            continue
        db.add(
            CheckSuggestion(
                category=r.category, content=r.content, kind=r.kind, goal=r.goal, unit=r.unit
            )
        )
        added += 1
    db.commit()
    return added


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    habits, habit_errors = parse_habits()
    cheers, cheer_errors = parse_cheers()
    errors = habit_errors + cheer_errors
    print(f"추천 습관 {len(habits)}개, 응원 문구 {len(cheers)}개를 읽었어요.")
    if errors:
        print(f"오류 {len(errors)}건 — 아무것도 넣지 않고 끝냅니다:")
        for e in errors:
            print(" -", e)
        return 1
    host = make_url(settings.database_url).host
    if not apply:
        print(f"검사만 했어요(대상 DB 호스트: {host}). 넣으려면 --apply 를 붙이세요.")
        return 0
    print(f"대상 DB 호스트: {host}")
    with SessionLocal() as db:
        added = insert_missing(db, habits + cheers)
    print(f"새로 넣은 문구 {added}개(이미 있던 {len(habits) + len(cheers) - added}개는 건너뜀).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
