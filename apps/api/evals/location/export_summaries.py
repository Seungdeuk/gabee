"""내 동선에서 평가용 요약 문장을 파일로 내보내는 일회용 스크립트(서버 코드를 바꾸지 않는다).

    cd apps/api && python -m evals.location.export_summaries --user <아이디|이메일|이름|id> --out <파일.json>
                    [--include-today] [--alias 원래이름=가린이름 ...] [--list-places]

하는 일
- 저장된 위치 점을 서버와 같은 규칙(timeline.convert)으로 하루 단위 구간으로 바꾸고, 같은 규칙(summary.build_chunks)으로 요약 문장을 만든다.
- 파일에는 좌표가 없다. 사람 이름은 "나"로 바꾸고, 장소는 사용자가 앱에서 붙인 이름만 쓴다(이름 없는 곳은 "이름 없는 곳").
  장소 이름 자체가 개인정보면 --alias 로 "집", "학원" 같은 이름으로 바꿔 내보낸다.
- 위치 점은 보관 기간(기본 14일)이 지나면 서버에서 지워지므로, 파일에는 하루 단위 구간을 쌓아 둔다. 같은 파일에 다시 실행하면
  그날의 구간만 새로 바꾸고 이미 지워진 날의 구간은 그대로 남는다. 보관 기간이 끝나기 전에 주기적으로 실행한다.
- 기록 없음(no_record)은 원인(여행 모드·앱 꺼짐·신호 없음)을 구분할 수 없어 요약 문장에서 뺀다.
- 아직 끝나지 않은 오늘과 보관 기간 때문에 앞부분이 잘렸을 수 있는 날은 내보내지 않는다.

주의
- 이 DB 는 환경변수 DATABASE_URL 이 가리키는 곳이다. 어느 DB 를 읽는지 먼저 출력한다. 읽기만 하고 쓰지 않는다.
- 출력 파일은 저장소 밖에 둔다(git 저장소 안이면 거부한다). 올리거나 공유하지 않는다.
- 요약 문장에는 날짜·요일·시각이 남는다. 좌표는 없다.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.features.location import repository as repo
from app.features.location import timeline as tl
from app.features.location import timeline_service as ts
from app.features.location.models import LocationPoint
from app.features.location.summary import Span, build_chunks
from app.shared.config import settings

VERSION = 1
ME = "나"
UNNAMED = "이름 없는 곳"


def parse_aliases(items: list[str]) -> dict[str, str]:
    """["원래=가림", ...] → {원래: 가림}. 모양이 틀리면 ValueError."""
    out: dict[str, str] = {}
    for item in items:
        old, sep, new = item.partition("=")
        if not sep or not old.strip() or not new.strip():
            raise ValueError(f"--alias 는 '원래이름=가린이름' 모양이어야 해요: {item!r}")
        out[old.strip()] = new.strip()
    return out


def find_user(db: Session, key: str) -> User:
    """아이디·이메일·이름·id 로 사용자 한 명을 찾는다. 없거나 여럿이면 ValueError."""
    rows = list(
        db.scalars(
            select(User).where(
                (User.id == key) | (User.login_id == key) | (User.email == key) | (User.name == key)
            )
        )
    )
    if len(rows) != 1:
        raise ValueError(
            f"'{key}' 와 맞는 사용자가 {len(rows)}명이에요. 아이디나 이메일로 다시 지정해 주세요"
        )
    return rows[0]


def exportable_days(
    db: Session, user_id: str, now: datetime, retention_days: int, include_today: bool
) -> list[date]:
    """내보낼 수 있는 날(KST). 보관 기간 때문에 앞부분이 잘렸을 수 있는 날과 (옵션이 없으면) 오늘은 뺀다."""
    kst = ts._kst()
    now_kst = now.astimezone(kst)
    cutoff = now_kst - timedelta(days=retention_days)
    first_full = cutoff.date() if cutoff.time() == time(0) else cutoff.date() + timedelta(days=1)
    first_point = db.scalar(
        select(func.min(LocationPoint.recorded_at)).where(LocationPoint.user_id == user_id)
    )
    if first_point is None:
        return []
    first = max(first_full, ts._as_utc(first_point).astimezone(kst).date())
    last = now_kst.date() if include_today else now_kst.date() - timedelta(days=1)
    days = []
    cur = first
    while cur <= last:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _naive_iso(d: datetime) -> str:
    return d.replace(tzinfo=None).isoformat(timespec="minutes")


def day_spans(
    db: Session, user: User, day: date, now: datetime, aliases: dict[str, str]
) -> list[dict] | None:
    """그날의 구간(기록 없음 제외). 그날 위치 점이 하나도 없으면 None(저장된 것을 건드리지 않는다)."""
    kst = ts._kst()
    start = datetime.combine(day, time(0), tzinfo=kst)
    end = min(start + timedelta(days=1), now.astimezone(kst))
    if end <= start:
        return None
    pts = ts._points(db, user.id, start, end)
    if not pts:
        return None
    segs = tl.convert(pts, ts._known(db, user.id), ts._zone_ref(db, user.id), (start, end))

    def alias(name: str | None) -> str | None:
        return aliases.get(name, name) if name else None

    return [
        {
            "kind": s.kind,
            "start": _naive_iso(s.start),
            "end": _naive_iso(s.end),
            "place": alias(s.place),
            "origin": alias(s.origin),
        }
        for s in segs
        if s.kind != "no_record"
    ]


def chunks_from_days(days: dict[str, list[dict]]) -> list[dict]:
    """쌓인 하루 구간들로 요약 조각을 다시 만든다(같은 입력이면 같은 결과)."""
    spans: list[Span] = []
    for day in sorted(days):
        for x in days[day]:
            move = x["kind"] == "move"
            named = x["kind"] in ("stay", "move")
            spans.append(
                Span(
                    "me",
                    ME,
                    datetime.fromisoformat(x["start"]),
                    datetime.fromisoformat(x["end"]),
                    x["kind"],
                    (x["place"] or UNNAMED) if named else None,
                    (x["origin"] or UNNAMED) if move else None,
                )
            )
    out = []
    for d in build_chunks(spans):
        out.append(
            {
                "key": f"{d.kind}|{d.starts_at.isoformat(timespec='minutes')}|{d.ends_at.isoformat(timespec='minutes')}|{d.place or ''}",
                "kind": d.kind,
                "starts_at": d.starts_at.isoformat(timespec="minutes"),
                "ends_at": d.ends_at.isoformat(timespec="minutes"),
                "place": d.place,
                "text": d.text,
            }
        )
    return out


def build_store(existing: dict | None, new_days: dict[str, list[dict]], now: datetime) -> dict:
    """기존 파일 내용에 새로 바꾼 날들을 덮어쓰고 조각을 다시 만든다."""
    days = dict((existing or {}).get("days", {}))
    days.update(new_days)
    days = dict(sorted(days.items()))
    return {
        "version": VERSION,
        "timezone": "KST(+09:00), 시각은 시간대 표시 없이 한국 시간",
        "person": ME,
        "exported_at": now.astimezone(UTC).isoformat(timespec="seconds"),
        "days": days,
        "chunks": chunks_from_days(days),
    }


def check_clean(text: str, forbidden: set[str]) -> None:
    """파일에 쓰기 전 마지막 점검: 실제 이름·id·가리기 전 장소 이름이 남아 있으면 중단한다."""
    leaked = sorted(f for f in forbidden if f and f in text)
    if leaked:
        raise ValueError(f"파일에 가려야 할 값이 남아 있어 쓰지 않았어요: {leaked}")


def inside_git_repo(path: Path) -> bool:
    for parent in [path.resolve(), *path.resolve().parents]:
        if (parent / ".git").exists():
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="내 동선의 요약 문장을 평가용 파일로 내보낸다")
    ap.add_argument("--user", required=True, help="아이디·이메일·이름·id 중 하나(본인 한 명)")
    ap.add_argument("--out", help="출력 파일(.json). 저장소 밖이어야 한다")
    ap.add_argument("--include-today", action="store_true", help="오늘(아직 끝나지 않은 날)도 포함")
    ap.add_argument(
        "--alias", action="append", default=[], help="장소 이름 바꾸기 '원래=가림' (여러 번 가능)"
    )
    ap.add_argument(
        "--list-places", action="store_true", help="내가 붙인 장소 이름만 보여 주고 끝낸다"
    )
    args = ap.parse_args(argv)

    from app.shared.db import SessionLocal, engine

    print(f"읽는 DB: {engine.url.render_as_string(hide_password=True)}")
    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = find_user(db, args.user)
        if args.list_places:
            names = [p.name for p in repo.list_places(db, user.id)]
            print("내가 붙인 장소 이름:", ", ".join(names) if names else "(없음)")
            return 0
        if not args.out:
            ap.error("--out 이 필요해요")
        out = Path(args.out)
        if inside_git_repo(out.parent if out.parent.exists() else out.parent.parent):
            print("출력 파일이 git 저장소 안이에요. 저장소 밖 경로를 쓰세요.", file=sys.stderr)
            return 2
        if user.location_consent_at is None:
            print("이 사용자는 위치 공유에 동의하지 않았어요.", file=sys.stderr)
            return 2
        aliases = parse_aliases(args.alias)
        days = exportable_days(
            db, user.id, now, settings.location_retention_days, args.include_today
        )
        new_days: dict[str, list[dict]] = {}
        for day in days:
            spans = day_spans(db, user, day, now, aliases)
            if spans is not None:
                new_days[day.isoformat()] = spans
        existing = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        store = build_store(existing, new_days, now)
        text = json.dumps(store, ensure_ascii=False, indent=1)
        check_clean(text, {user.name, user.id, user.login_id or "", user.email or "", *aliases})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(
        f"저장: {out} (새로 바꾼 날 {len(new_days)}일, 파일 전체 {len(store['days'])}일, 요약 조각 {len(store['chunks'])}개)"
    )
    if new_days:
        oldest = min(new_days)
        print(
            f"서버에서 가장 오래된 내보낸 날: {oldest} → 이 날은 보관 기간이 끝나면 서버에서 사라져요. 파일에는 남아요"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
