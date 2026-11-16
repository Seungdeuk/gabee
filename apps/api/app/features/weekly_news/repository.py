from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import MemberWeeklyNews


def get_for_member(
    db: Session, group_id: str, user_id: str, week_start: date
) -> MemberWeeklyNews | None:
    """그 가족의 그 구성원의 그 주 저장본. 세 값이 모두 맞아야만 찾는다."""
    return db.scalar(
        select(MemberWeeklyNews).where(
            MemberWeeklyNews.group_id == group_id,
            MemberWeeklyNews.user_id == user_id,
            MemberWeeklyNews.week_start == week_start,
        )
    )


def delete_for_member(db: Session, group_id: str, user_id: str) -> int:
    """그 가족에서 그 구성원의 뉴스 줄을 모두 지운다(가족을 나갈 때). 다른 가족의 줄과 다른 구성원의 줄은 건드리지 않는다."""
    result = db.execute(
        delete(MemberWeeklyNews).where(
            MemberWeeklyNews.group_id == group_id, MemberWeeklyNews.user_id == user_id
        )
    )
    return result.rowcount or 0


def is_stale(row: MemberWeeklyNews, now: datetime, age: timedelta) -> bool:
    """만드는 중인 줄이 `age` 보다 오래됐는가(서버가 죽어 pending 이 남은 경우)."""
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return now - updated >= age


def claim(
    db: Session, group_id: str, user_id: str, week_start: date, now: datetime, stale: timedelta
) -> MemberWeeklyNews | None:
    """그 주 줄을 `pending` 으로 차지한다. 이미 `ok`·만드는 중(오래되지 않음)이면 None.

    줄이 없으면 새로 넣고(유일 키가 동시 요청을 막는다), `failed`·`empty`·오래된 `pending` 은 조건부 UPDATE 로 가져온다.
    """
    row = get_for_member(db, group_id, user_id, week_start)
    if row is None:
        row = MemberWeeklyNews(
            group_id=group_id,
            user_id=user_id,
            week_start=week_start,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return row
    if row.status == "ok" or (row.status == "pending" and not is_stale(row, now, stale)):
        return None
    old, seen = row.status, row.updated_at
    result = db.execute(
        update(MemberWeeklyNews)
        .where(
            MemberWeeklyNews.id == row.id,
            MemberWeeklyNews.status == old,
            # 오래된 pending 을 두 요청이 동시에 차지하지 못하게: 읽은 시점 그대로일 때만 가져온다
            MemberWeeklyNews.updated_at == seen,
        )
        .values(
            status="pending",
            body=None,
            sources=None,
            error_code=None,
            updated_at=now,
        )
    )
    db.commit()
    if result.rowcount != 1:
        return None
    db.refresh(row)
    return row


def snapshot(row: MemberWeeklyNews | None) -> dict | None:
    """차지하기 전 `failed`·`empty` 줄의 상태(되돌릴 때 쓴다). 그 밖(없음·오래된 pending)은 None."""
    if row is None or row.status not in ("failed", "empty"):
        return None
    return {
        "status": row.status,
        "error_code": row.error_code,
        "model": row.model,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "updated_at": row.updated_at,
    }


def release_claim(
    db: Session, group_id: str, user_id: str, week_start: date, previous: dict | None = None
) -> None:
    """차지했던 `pending` 을 놓는다(한도 초과 등으로 만들지 못했을 때). 전에 `failed`·`empty` 였으면 그 상태로 되돌리고,
    없던 줄이면 지운다(나중에 다시 눌러 볼 수 있게)."""
    db.rollback()
    where = (
        MemberWeeklyNews.group_id == group_id,
        MemberWeeklyNews.user_id == user_id,
        MemberWeeklyNews.week_start == week_start,
        MemberWeeklyNews.status == "pending",
    )
    if previous is None:
        db.execute(delete(MemberWeeklyNews).where(*where))
    else:
        db.execute(update(MemberWeeklyNews).where(*where).values(**previous))
    db.commit()


def _upsert(db: Session, group_id: str, user_id: str, week_start: date, now: datetime, **values):
    row = get_for_member(db, group_id, user_id, week_start)
    if row is None:
        row = MemberWeeklyNews(
            group_id=group_id,
            user_id=user_id,
            week_start=week_start,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def _finish(
    db: Session,
    group_id: str,
    user_id: str,
    week_start: date,
    now: datetime,
    claimed_at: datetime | None,
    **values,
) -> MemberWeeklyNews | None:
    """결과를 저장한다. `claimed_at`(내가 차지한 시각)을 주면 **그 줄이 아직 내가 차지한 그대로일 때만** 저장하고, 아니면 None 이다.
    생성 도중 가족을 나가 줄이 지워졌거나(새로 만들면 나간 사람의 뉴스가 되살아난다), 차지를 다른 요청이 넘겨받은 경우다.
    `claimed_at` 이 None 이면 줄이 없어도 만든다(시험 준비용)."""
    if claimed_at is None:
        return _upsert(db, group_id, user_id, week_start, now, **values)
    result = db.execute(
        update(MemberWeeklyNews)
        .where(
            MemberWeeklyNews.group_id == group_id,
            MemberWeeklyNews.user_id == user_id,
            MemberWeeklyNews.week_start == week_start,
            MemberWeeklyNews.status == "pending",
            MemberWeeklyNews.updated_at == claimed_at,
        )
        .values(**values, updated_at=now)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    db.expire_all()  # 대량 UPDATE 는 세션이 들고 있는 옛 객체를 고치지 않는다: 저장된 모습을 새로 읽는다
    return get_for_member(db, group_id, user_id, week_start)


def save_status(
    db: Session,
    group_id: str,
    user_id: str,
    week_start: date,
    status: str,
    error_code: str | None,
    now: datetime,
    *,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    claimed_at: datetime | None = None,
) -> MemberWeeklyNews | None:
    """`failed`·`empty` 로 저장한다(문장·근거 없음, 고정 오류 코드만). `claimed_at` 은 `_finish` 참고."""
    return _finish(
        db,
        group_id,
        user_id,
        week_start,
        now,
        claimed_at,
        status=status,
        body=None,
        sources=None,
        error_code=error_code,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def save_ok(
    db: Session,
    group_id: str,
    user_id: str,
    week_start: date,
    *,
    body: dict,
    sources: list,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    now: datetime,
    claimed_at: datetime | None = None,
) -> MemberWeeklyNews | None:
    return _finish(
        db,
        group_id,
        user_id,
        week_start,
        now,
        claimed_at,
        status="ok",
        body=body,
        sources=sources,
        error_code=None,
        model=model[:60],
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def member_names(db: Session, group_id: str) -> list[tuple[str, ...]]:
    """가족 구성원의 이름 사전. 한 사람은 (표시 이름, 실제 이름) 묶음이고 첫 번째가 대표 이름이다(표시 이름이 없으면 실제 이름). 저장되는 문장에는 대표 이름이 들어간다. 정렬해 같은 구성이면 같은 순서."""
    rows = db.execute(
        select(User.name, GroupMember.display_name)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
    ).all()
    people: set[tuple[str, ...]] = set()
    for name, display in rows:
        real = " ".join((name or "").split())
        shown = " ".join((display or "").split())
        if real:
            people.add((shown, real) if shown and shown != real else (real,))
        elif shown:
            people.add((shown,))
    return sorted(people)
