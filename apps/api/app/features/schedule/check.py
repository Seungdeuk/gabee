"""데일리 체크 서비스: 내 습관과 날짜별 기록, 가족 조회·요약, 응원, 온보딩 표시.

- "오늘"과 "지금"은 서버 시계의 한국 시간(`timeutil.local_tz`)이다. 기록·조회 날짜(`date`)는 선택이고, 없으면 오늘이다.
- 날짜 규칙: 기록·조회 날짜는 오늘부터 7일 전까지만 쓴다(그 밖·미래는 400). 기록은 추가로 습관을 만든 날(한국 날짜)
  이전이면 400 이다. 반복 요일은 목록에 나올지에만 쓰고 기록 가능 여부와는 무관하다.
- 기록 줄(`CheckLog`)은 습관 하루에 한 줄이고, 그날 처음 체크·횟수·메모를 남길 때만 만든다. 지난 줄은 목표 변경으로 바뀌지 않는다.
  목표를 바꾸면 오늘 줄만 goal 스냅샷과 완료 여부를 다시 계산한다.
- 습관 삭제는 `deleted_at` 소프트 삭제다. 지운 습관은 목록·기록에서 빠지고 지난 줄은 남는다.
- 습관·응원은 사람(user_id)에게 묶인다. 가족 단위 판단(누가 가족 구성원인가)은 `group_members` 로 그때그때 한다:
  가족 조회와 응원 보내기는 요청자의 현재 그룹을 기준으로 본다.
- 고마워·닫기는 "보내면 끝"이다. 처음 한 번만 시각을 넣고, 이미 있으면 그대로 둔다(되돌림 없음).
- 시계는 `now_utc()` 한 곳에서 읽는다. 시험은 이 함수를 바꿔 날짜 경계를 확인한다.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared.errors import bad_request, not_found

from . import check_repository as repo
from .check_schemas import (
    CheckCheerCreate,
    CheckEntryBody,
    CheckItemCreate,
    CheckItemUpdate,
    CheckNoteBody,
    CheckSettingsIn,
)
from .constants import CHECK_DAY_RANGE, CHECK_KIND_CHECK, CHECK_KIND_COUNT
from .models import CheckCheer, CheckItem, CheckLog, CheckSetting
from .timeutil import local_tz


def now_utc() -> datetime:
    """지금 시각(시간대 포함). 시험에서는 이 함수를 바꿔 시계를 옮긴다."""
    return datetime.now(UTC)


def _now() -> datetime:
    """저장할 때는 항상 UTC 로 바꾼다(SQLite 는 시간대를 버리므로 한국 시각을 그대로 넣으면 날짜가 어긋난다)."""
    return now_utc().astimezone(UTC)


def _aware(value: datetime) -> datetime:
    """SQLite 에서 읽은 값은 시간대가 없다. 저장할 때 UTC 로 넣었으므로 없으면 UTC 로 본다."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def today_of(now: datetime) -> date:
    """한국 시간 기준 오늘 날짜."""
    return _aware(now).astimezone(local_tz()).date()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _applies(item: CheckItem, day: date, log: CheckLog | None) -> bool:
    """그 날짜 목록에 나오는가(요일 기준). 반복 요일을 마지막으로 바꾼 날(KST) 이후거나 바꾼 적이 없으면 현재 요일 비트를 본다.
    그보다 앞 날짜는 예전 요일을 모르므로, 그 날짜에 기록 줄이 있는 습관만 켜진 것으로 본다.
    습관을 만든 날(KST)보다 앞 날짜는 기록할 수 없으므로 목록에도 나오지 않는다.
    월~일 순서, 월 = 첫 글자(weekday() 는 월요일이 0)."""
    if day < today_of(_aware(item.created_at)):
        return False
    if item.repeat_updated_at is None or day >= today_of(item.repeat_updated_at):
        return item.repeat_days[day.weekday()] == "1"
    return log is not None


def _view_day(day: date | None, now: datetime) -> date:
    """조회 날짜: 없으면 오늘. 오늘~7일 전 밖이면 400(반복 요일·생성일은 조회에서 보지 않는다)."""
    today = today_of(now)
    day = day or today
    if not today - timedelta(days=CHECK_DAY_RANGE) <= day <= today:
        raise bad_request("date_out_of_range", "기록은 오늘부터 7일 전까지의 날짜만 볼 수 있어요")
    return day


def _entry_day(item: CheckItem, day: date | None, now: datetime) -> date:
    """기록 날짜: 조회 범위(오늘~7일 전)를 지키고, 습관을 만든 날(한국 날짜) 이후여야 한다.
    반복 요일은 기록 가능 여부와 무관하다(목록에 나올지에만 쓴다)."""
    day = _view_day(day, now)
    if day < today_of(_aware(item.created_at)):
        raise bad_request("before_item_created", "습관을 만들기 전 날짜에는 기록할 수 없어요")
    return day


def _record(item: CheckItem, log: CheckLog | None) -> dict:
    """그날 상태. 줄이 없으면 미완료·0·메모 없음. 체크 습관은 done, 횟수 습관은 count 만 값이 있다."""
    confirmed = bool(log and log.confirmed)
    stamp = _aware(log.confirmed_at) if log and log.confirmed_at else None
    note = log.note if log and log.note else None
    if item.kind == CHECK_KIND_CHECK:
        done, count = bool(log and log.done), None
    else:
        done, count = None, (log.count or 0) if log else 0
    return {
        "done": done,
        "count": count,
        "confirmed": confirmed,
        "confirmed_at": stamp,
        "note": note,
        "note_shared": bool(note and log.note_shared),
    }


def _item_out(item: CheckItem, log: CheckLog | None, day: date) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "goal": item.goal,
        "unit": item.unit or "",
        "repeat_days": item.repeat_days,
        "shared": item.shared,
        "notify": item.notify,
        "position": item.position,
        "applies": _applies(item, day, log),
        "updated_at": _aware(item.updated_at),
        **_record(item, log),
    }


def _member_item_out(item: CheckItem, log: CheckLog | None) -> dict:
    """가족에게 보이는 줄: 알림·순서·반복 요일은 싣지 않는다. 메모는 습관과 줄이 모두 공유일 때만 싣는다."""
    record = _record(item, log)
    note = record["note"] if item.shared and record["note_shared"] else None
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "goal": item.goal,
        "unit": item.unit or "",
        "done": record["done"],
        "count": record["count"],
        "confirmed": record["confirmed"],
        "confirmed_at": record["confirmed_at"],
        "note": note,
    }


def _owned(db: Session, user_id: str, item_id: str) -> CheckItem:
    item = repo.item_of(db, user_id, item_id)
    if item is None:
        raise not_found("습관")
    return item


def _check_repeat(repeat_days: str) -> None:
    if "1" not in repeat_days:
        raise bad_request("invalid_repeat", "반복 요일을 하루 이상 골라 주세요")


def _new_log(item: CheckItem, day: date, now: datetime) -> CheckLog:
    """그날 줄을 처음 만든다. 이후 created_at 은 바뀌지 않는다."""
    return CheckLog(
        id=_new_id(),
        item_id=item.id,
        log_date=day,
        done=None,
        count=None,
        goal=None,
        confirmed=False,
        note=None,
        note_shared=False,
        confirmed_at=None,
        created_at=now,
    )


def _apply_count_state(log: CheckLog, goal: int, now: datetime) -> None:
    """횟수 완료 상태. 목표에 처음 닿을 때만 완료 시각을 찍고, 이미 완료면 시각을 바꾸지 않는다.
    목표 아래로 내려가면 완료를 취소하고 시각을 지운다."""
    if (log.count or 0) >= goal:
        if not log.confirmed or log.confirmed_at is None:
            log.confirmed, log.confirmed_at = True, now
    else:
        log.confirmed, log.confirmed_at = False, None


# ---------------------------------------------------------------- 내 습관
def list_items(db: Session, user_id: str, day: date | None = None) -> list[dict]:
    view = _view_day(day, _now())
    items = repo.items_of(db, user_id)
    logs = repo.logs_on(db, [i.id for i in items], view)
    return [_item_out(i, logs.get(i.id), view) for i in items]


def create_item(db: Session, user_id: str, body: CheckItemCreate) -> dict:
    if body.kind == CHECK_KIND_CHECK:
        if body.goal is not None or body.unit:
            raise bad_request("invalid_field", "체크 습관에는 목표와 단위를 둘 수 없어요")
        goal = None
    else:
        if body.goal is None:
            raise bad_request("goal_required", "횟수 습관에는 하루 목표가 필요해요")
        goal = body.goal
    _check_repeat(body.repeat_days)
    last = repo.max_position(db, user_id)
    item = CheckItem(
        id=_new_id(),
        user_id=user_id,
        name=body.name,
        kind=body.kind,
        goal=goal,
        unit=body.unit,
        repeat_days=body.repeat_days,
        shared=body.shared,
        notify=body.notify,
        position=0 if last is None else last + 1,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(item)
    db.commit()
    return _item_out(item, None, today_of(_now()))


def update_item(db: Session, user_id: str, item_id: str, body: CheckItemUpdate) -> dict:
    item = _owned(db, user_id, item_id)
    now = _now()
    today = today_of(now)
    sent = body.model_fields_set
    old_kind, old_goal = item.kind, item.goal
    old_repeat = item.repeat_days
    before = (
        item.name,
        item.kind,
        item.goal,
        item.unit,
        item.repeat_days,
        item.shared,
        item.notify,
    )
    new_kind = body.kind if body.kind is not None else item.kind

    # 종류·목표·단위 규칙: 체크 습관에는 목표·단위가 없고, 횟수 습관에는 목표가 있다
    if new_kind == CHECK_KIND_CHECK:
        if body.goal is not None or body.unit:
            raise bad_request("invalid_field", "체크 습관에는 목표와 단위를 둘 수 없어요")
        goal, unit = None, ""
    else:
        goal = body.goal if "goal" in sent else item.goal
        if goal is None:
            raise bad_request("goal_required", "횟수 습관에는 하루 목표가 필요해요")
        unit = body.unit if body.unit is not None else (item.unit or "")
    if body.repeat_days is not None:
        _check_repeat(body.repeat_days)

    if body.name is not None:
        item.name = body.name
    item.kind, item.goal, item.unit = new_kind, goal, unit
    if body.repeat_days is not None and body.repeat_days != old_repeat:
        item.repeat_updated_at = now  # 값이 실제로 달라졌을 때만 시각을 갱신한다
        item.repeat_days = body.repeat_days
    if body.shared is not None:
        item.shared = body.shared
    if body.notify is not None:
        item.notify = body.notify

    after = (item.name, item.kind, item.goal, item.unit, item.repeat_days, item.shared, item.notify)
    if after != before:
        item.updated_at = now  # 정의가 실제로 바뀐 경우에만 수정 시각을 갱신한다

    log = repo.log_of(db, item.id, today)  # 지난 줄은 건드리지 않는다
    if log is not None:
        if new_kind != old_kind:
            # 종류가 바뀌면 오늘 줄의 기록을 비우고 메모만 남긴다
            log.done, log.count, log.goal = None, None, None
            log.confirmed, log.confirmed_at = False, None
        elif new_kind == CHECK_KIND_COUNT and goal != old_goal:
            # 목표를 바꾸면 오늘 횟수는 깎지 않고 목표·완료 여부만 다시 계산한다
            log.goal = goal
            _apply_count_state(log, goal, now)
    db.commit()
    return _item_out(item, log, today)


def delete_item(db: Session, user_id: str, item_id: str) -> None:
    """소프트 삭제: 습관에 `deleted_at` 을 채운다. 지난 기록 줄은 그대로 남긴다."""
    item = _owned(db, user_id, item_id)
    item.deleted_at = _now()
    db.commit()


def reorder_items(db: Session, user_id: str, ids: list[str]) -> list[dict]:
    """내 습관(지워지지 않은 것) 전체의 새 순서를 0..N-1 로 한 번에 다시 매긴다."""
    items = {i.id: i for i in repo.items_of(db, user_id)}
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        raise bad_request(
            "invalid_order", "습관 전체의 순서를 한 번에 보내 주세요(누락·중복·남의 습관은 안 돼요)"
        )
    for position, item_id in enumerate(ids):
        items[item_id].position = position
    db.commit()
    today = today_of(_now())
    logs = repo.logs_on(db, ids, today)
    return [_item_out(items[i], logs.get(i), today) for i in ids]


def set_entry(
    db: Session, user_id: str, item_id: str, body: CheckEntryBody, day: date | None = None
) -> dict:
    """그날 기록. 체크 습관은 done(참·거짓), 횟수 습관은 count(절대값)를 보낸다. 종류와 맞지 않는 필드는 400."""
    item = _owned(db, user_id, item_id)
    now = _now()
    target = _entry_day(item, day, now)
    log = repo.log_of(db, item.id, target)
    if item.kind == CHECK_KIND_CHECK:
        if body.done is None or body.count is not None:
            raise bad_request("invalid_entry", "체크 습관은 done 만 보낼 수 있어요")
        if body.done:
            if log is None:
                log = _new_log(item, target, now)
                db.add(log)
            if not log.done:  # 이미 체크돼 있으면 처음 체크한 시각을 그대로 둔다
                log.done, log.confirmed, log.confirmed_at = True, True, now
        elif log is not None:
            log.done, log.confirmed, log.confirmed_at = False, False, None
    else:
        if body.count is None or body.done is not None:
            raise bad_request("invalid_entry", "횟수 습관은 count 만 보낼 수 있어요")
        if log is None:
            if body.count == 0:  # 0 을 적는 것은 기록이 아니므로 줄을 만들지 않는다
                return _item_out(item, None, target)
            log = _new_log(item, target, now)
            db.add(log)
        log.count, log.done, log.goal = body.count, None, item.goal
        _apply_count_state(log, item.goal, now)
    db.commit()
    return _item_out(item, log, target)


def set_note(
    db: Session, user_id: str, item_id: str, body: CheckNoteBody, day: date | None = None
) -> dict:
    """그날 메모 저장·지우기. 빈 값이면 메모를 지운다(줄은 남긴다). 기록할 것이 없는 날의 지우기는 줄을 만들지 않는다."""
    item = _owned(db, user_id, item_id)
    now = _now()
    target = _entry_day(item, day, now)
    log = repo.log_of(db, item.id, target)
    if body.note is None:
        if log is not None:
            log.note, log.note_shared = None, False
    else:
        if log is None:
            log = _new_log(item, target, now)
            db.add(log)
        log.note, log.note_shared = body.note, body.note_shared
    db.commit()
    return _item_out(item, log, target)


# ---------------------------------------------------------------- 가족
def members_summary(db: Session, group_id: str) -> list[dict]:
    """요청자의 현재 그룹 구성원 전원(본인 포함)의 [오늘 해당하는 가족에게 보이는 습관 수, 그중 오늘 완료 수]."""
    today = today_of(_now())
    members = repo.members_of(db, group_id)
    flags: dict[str, list[bool]] = {user_id: [] for user_id, _ in members}
    shared = repo.shared_items_of(db, list(flags))
    logs = repo.logs_on(db, [i.id for i in shared], today)
    for item in shared:
        if _applies(item, today, logs.get(item.id)):
            flags[item.user_id].append(_record(item, logs.get(item.id))["confirmed"])
    return [
        {
            "user_id": user_id,
            "name": name,
            "total": len(flags[user_id]),
            "done": sum(flags[user_id]),
        }
        for user_id, name in members
    ]


def member_today(db: Session, group_id: str, target_id: str) -> dict:
    """대상이 요청자의 현재 그룹 구성원일 때만 보여 준다. 아니면 존재를 알리지 않고 404 다."""
    if not repo.is_member(db, group_id, target_id):
        raise not_found("구성원")
    today = today_of(_now())
    name = repo.names_of(db, {target_id}).get(target_id, "")
    shared = repo.shared_items_of(db, [target_id])
    logs = repo.logs_on(db, [i.id for i in shared], today)
    items = [i for i in shared if _applies(i, today, logs.get(i.id))]
    return {
        "user_id": target_id,
        "name": name,
        "items": [_member_item_out(i, logs.get(i.id)) for i in items],
    }


# ---------------------------------------------------------------- 응원
def _cheer_out(cheer: CheckCheer, names: dict[str, str]) -> dict:
    return {
        "id": cheer.id,
        "from_user_id": cheer.from_user_id,
        "from_name": names.get(cheer.from_user_id, ""),
        "to_user_id": cheer.to_user_id,
        "to_name": names.get(cheer.to_user_id, ""),
        "kind": cheer.kind,
        "message": cheer.message,
        "chat_left": cheer.chat_left,
        "sent_at": _aware(cheer.sent_at),
        "thanked_at": _aware(cheer.thanked_at) if cheer.thanked_at else None,
        "closed": cheer.closed_at is not None,
        "closed_at": _aware(cheer.closed_at) if cheer.closed_at else None,
    }


def _cheer_outs(db: Session, cheers: list[CheckCheer]) -> list[dict]:
    ids = {c.from_user_id for c in cheers} | {c.to_user_id for c in cheers}
    names = repo.names_of(db, ids)
    return [_cheer_out(c, names) for c in cheers]


def send_cheer(db: Session, group_id: str, user_id: str, body: CheckCheerCreate) -> dict:
    """받는 사람은 요청자의 현재 그룹 구성원이어야 한다. 자기 자신에게는 보낼 수 없다."""
    if body.to_user_id == user_id:
        raise bad_request("self_cheer", "자기 자신에게는 응원을 보낼 수 없어요")
    if not repo.is_member(db, group_id, body.to_user_id):
        raise not_found("구성원")
    cheer = CheckCheer(
        id=_new_id(),
        from_user_id=user_id,
        to_user_id=body.to_user_id,
        kind=body.kind,
        message=body.message,
        chat_left=body.chat_left,
        sent_at=_now(),
    )
    db.add(cheer)
    db.commit()
    return _cheer_outs(db, [cheer])[0]


def list_cheers(db: Session, user_id: str, direction: str) -> list[dict]:
    """received: 내가 받은 응원, sent: 내가 보낸 응원. 닫힌 카드도 남기고 closed 로 구분한다."""
    if direction == "sent":
        return _cheer_outs(db, repo.cheers_sent(db, user_id))
    return _cheer_outs(db, repo.cheers_received(db, user_id))


def _received(db: Session, user_id: str, cheer_id: str) -> CheckCheer:
    """받은 사람만 고마워·닫기를 할 수 있다. 보낸 사람과 제3자에게는 없는 것처럼 404."""
    cheer = repo.cheer_of(db, cheer_id)
    if cheer is None or cheer.to_user_id != user_id:
        raise not_found("응원")
    return cheer


def set_thanked(db: Session, user_id: str, cheer_id: str) -> dict:
    """고마워 보내기. 처음 한 번만 시각을 넣고, 이미 있으면 그대로 둔다(되돌림 없음)."""
    cheer = _received(db, user_id, cheer_id)
    if cheer.thanked_at is None:
        cheer.thanked_at = _now()
        db.commit()
    return _cheer_outs(db, [cheer])[0]


def close_cheer(db: Session, user_id: str, cheer_id: str) -> dict:
    """카드 닫기. 처음 한 번만 시각을 넣고, 이미 닫혀 있으면 그대로 둔다(되돌림 없음)."""
    cheer = _received(db, user_id, cheer_id)
    if cheer.closed_at is None:
        cheer.closed_at = _now()
        db.commit()
    return _cheer_outs(db, [cheer])[0]


# ---------------------------------------------------------------- 설정
def get_settings(db: Session, user_id: str) -> dict:
    row = repo.setting_of(db, user_id)
    return {"onboarded": bool(row and row.onboarded)}


def set_settings(db: Session, user_id: str, body: CheckSettingsIn) -> dict:
    row = repo.setting_of(db, user_id)
    if row is None:
        db.add(CheckSetting(user_id=user_id, onboarded=body.onboarded))
    else:
        row.onboarded = body.onboarded
    db.commit()
    return {"onboarded": body.onboarded}
