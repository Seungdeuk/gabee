"""데일리 체크 서비스: 내 습관과 오늘 기록, 가족 조회·요약, 응원, 온보딩 표시.

- 날짜는 서버가 정한다. "오늘"과 "지금"은 서버 시계의 한국 시간(`timeutil.local_tz`)이다. 요청에는 날짜가 없다.
- 오늘 기록의 유효성: `confirmed_at` 의 한국 날짜가 오늘일 때만 done·count·confirmed 를 그대로 보여 준다. 아니면 미완료·0·거짓.
  DB 값은 날짜가 바뀌어도 지우지 않는다(초기화 작업 없음). 그래서 자정이 지나면 어제 기록은 자연히 안 보인다.
- 습관·응원은 사람(user_id)에게 묶인다. 가족 단위 판단(누가 가족 구성원인가)은 `group_members` 로 그때그때 한다:
  가족 조회와 응원 보내기는 요청자의 현재 그룹을 기준으로 본다.
- 고마워·닫기는 "보내면 끝"이다. 처음 한 번만 시각을 넣고, 이미 있으면 그대로 둔다(되돌림 없음).
- 시계는 `now_utc()` 한 곳에서 읽는다. 시험은 이 함수를 바꿔 자정 경계를 확인한다.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.shared.errors import bad_request, not_found

from . import check_repository as repo
from .check_schemas import (
    CheckCheerCreate,
    CheckEntryBody,
    CheckItemCreate,
    CheckItemUpdate,
    CheckSettingsIn,
)
from .constants import CHECK_KIND_CHECK, CHECK_KIND_COUNT
from .models import CheckCheer, CheckItem, CheckSetting
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


def _valid_today(item: CheckItem, today: date) -> bool:
    """오늘 기록인가: 기록 시각의 한국 날짜가 오늘과 같은가."""
    return item.confirmed_at is not None and today_of(item.confirmed_at) == today


def _repeats_on(item: CheckItem, today: date) -> bool:
    """반복 요일: 월~일 순서의 1/0 문자열, 월 = 첫 글자(weekday() 는 월요일이 0)."""
    return item.repeat_days[today.weekday()] == "1"


def _record(item: CheckItem, today: date) -> dict:
    """오늘 상태(유효성을 반영한 값). 체크 습관은 done, 횟수 습관은 count 만 값이 있다."""
    valid = _valid_today(item, today)
    stamp = _aware(item.confirmed_at) if valid else None
    if item.kind == CHECK_KIND_CHECK:
        return {
            "done": valid and bool(item.done),
            "count": None,
            "confirmed": valid and bool(item.confirmed),
            "confirmed_at": stamp,
        }
    return {
        "done": None,
        "count": (item.count or 0) if valid else 0,
        "confirmed": valid and bool(item.confirmed),
        "confirmed_at": stamp,
    }


def _item_out(item: CheckItem, today: date) -> dict:
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
        **_record(item, today),
    }


def _member_item_out(item: CheckItem, today: date) -> dict:
    """가족에게 보이는 줄: 알림·순서·반복 요일은 싣지 않는다."""
    return {
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "goal": item.goal,
        "unit": item.unit or "",
        **_record(item, today),
    }


def _owned(db: Session, user_id: str, item_id: str) -> CheckItem:
    item = repo.item_of(db, user_id, item_id)
    if item is None:
        raise not_found("습관")
    return item


def _check_repeat(repeat_days: str) -> None:
    if "1" not in repeat_days:
        raise bad_request("invalid_repeat", "반복 요일을 하루 이상 골라 주세요")


# ---------------------------------------------------------------- 내 습관
def list_items(db: Session, user_id: str) -> list[dict]:
    today = today_of(_now())
    return [_item_out(i, today) for i in repo.items_of(db, user_id)]


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
    is_check = body.kind == CHECK_KIND_CHECK
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
        done=False if is_check else None,
        count=None if is_check else 0,
        confirmed=False,
        confirmed_at=None,
        created_at=_now(),
    )
    db.add(item)
    db.commit()
    return _item_out(item, today_of(_now()))


def _reset_today(item: CheckItem) -> None:
    """종류를 바꾸면 오늘 기록(done·count·confirmed·confirmed_at)을 비운다."""
    item.done = False if item.kind == CHECK_KIND_CHECK else None
    item.count = None if item.kind == CHECK_KIND_CHECK else 0
    item.confirmed = False
    item.confirmed_at = None


def update_item(db: Session, user_id: str, item_id: str, body: CheckItemUpdate) -> dict:
    item = _owned(db, user_id, item_id)
    today = today_of(_now())
    sent = body.model_fields_set
    old_kind, old_goal = item.kind, item.goal
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
    if body.repeat_days is not None:
        item.repeat_days = body.repeat_days
    if body.shared is not None:
        item.shared = body.shared
    if body.notify is not None:
        item.notify = body.notify

    if new_kind != old_kind:
        _reset_today(item)  # 종류가 바뀌면 오늘 기록을 초기화한다
    elif new_kind == CHECK_KIND_COUNT and goal != old_goal:
        # 목표를 바꾸면 오늘 횟수는 깎지 않고 완료 여부만 다시 계산한다
        if _valid_today(item, today):
            item.confirmed = (item.count or 0) >= goal
        else:
            item.confirmed = False
    db.commit()
    return _item_out(item, today)


def delete_item(db: Session, user_id: str, item_id: str) -> None:
    item = _owned(db, user_id, item_id)
    db.delete(item)  # 소프트 삭제가 아니라 행을 지운다
    db.commit()


def reorder_items(db: Session, user_id: str, ids: list[str]) -> list[dict]:
    """내 습관 전체의 새 순서를 0..N-1 로 한 번에 다시 매긴다."""
    items = {i.id: i for i in repo.items_of(db, user_id)}
    if len(ids) != len(set(ids)) or set(ids) != set(items):
        raise bad_request(
            "invalid_order", "습관 전체의 순서를 한 번에 보내 주세요(누락·중복·남의 습관은 안 돼요)"
        )
    for position, item_id in enumerate(ids):
        items[item_id].position = position
    db.commit()
    today = today_of(_now())
    return [_item_out(items[i], today) for i in ids]


def set_entry(db: Session, user_id: str, item_id: str, body: CheckEntryBody) -> dict:
    """오늘 기록. 체크 습관은 done(참·거짓), 횟수 습관은 count(절대값)를 보낸다. 종류와 맞지 않는 필드는 400."""
    item = _owned(db, user_id, item_id)
    now = _now()
    if item.kind == CHECK_KIND_CHECK:
        if body.done is None or body.count is not None:
            raise bad_request("invalid_entry", "체크 습관은 done 만 보낼 수 있어요")
        if body.done:
            item.done, item.confirmed, item.confirmed_at = True, True, now
        else:
            item.done, item.confirmed, item.confirmed_at = False, False, None
    else:
        if body.count is None or body.done is not None:
            raise bad_request("invalid_entry", "횟수 습관은 count 만 보낼 수 있어요")
        item.count, item.done = body.count, None
        if body.count == 0:
            item.confirmed, item.confirmed_at = False, None
        else:
            item.confirmed = body.count >= (item.goal or 0)
            item.confirmed_at = now
    db.commit()
    return _item_out(item, today_of(now))


# ---------------------------------------------------------------- 가족
def members_summary(db: Session, group_id: str) -> list[dict]:
    """요청자의 현재 그룹 구성원 전원(본인 포함)의 [오늘 해당하는 가족에게 보이는 습관 수, 그중 오늘 완료 수]."""
    today = today_of(_now())
    members = repo.members_of(db, group_id)
    flags: dict[str, list[bool]] = {user_id: [] for user_id, _ in members}
    for item in repo.shared_items_of(db, list(flags)):
        if _repeats_on(item, today):
            flags[item.user_id].append(_record(item, today)["confirmed"])
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
    items = [i for i in repo.shared_items_of(db, [target_id]) if _repeats_on(i, today)]
    return {
        "user_id": target_id,
        "name": name,
        "items": [_member_item_out(i, today) for i in items],
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
