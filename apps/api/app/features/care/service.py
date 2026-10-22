import re
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.location_consent import set_location_consent

from . import config
from . import repository as repo
from .models import KINDS, CareEntry, CareItem, CareLocation, CareRecord
from .schemas import (
    ConsentOut,
    DailyOut,
    EntryOut,
    EntryPut,
    ItemCreate,
    ItemOut,
    LocationBatch,
    LocationSaved,
    LocationsLatest,
    MealList,
    MealOut,
    MemberLocation,
    PutResult,
    RecommendationList,
    RecommendationOut,
    RecordOut,
    RecordPut,
    TodaySummary,
)

KST = timezone(timedelta(hours=9))
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _out(r: CareRecord) -> RecordOut:
    return RecordOut(
        id=r.id,
        subject=r.subject,
        kind=r.kind,
        value=r.value,
        note=r.note,
        date=r.date,
        created_by=r.created_by,
    )


def put(db: Session, group_id: str, user_id: str, body: RecordPut) -> PutResult:
    day = (body.date or datetime.now(KST).date()).isoformat()
    existing = repo.find(db, group_id, body.subject.strip(), body.kind, day)
    if existing:
        existing.value, existing.note, existing.created_by = body.value, body.note, user_id
        existing.updated_at = datetime.now(UTC)
        return PutResult(record=_out(repo.save(db, existing)), replaced=True)
    record = CareRecord(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        subject=body.subject.strip(),
        kind=body.kind,
        value=body.value,
        note=body.note,
        date=day,
        created_by=user_id,
    )
    return PutResult(record=_out(repo.save(db, record)), replaced=False)


def list_day(db: Session, group_id: str, day: str | None) -> list[RecordOut]:
    return [_out(r) for r in repo.list_day(db, group_id, day or today_kst())]


def today_summary(db: Session, group_id: str) -> TodaySummary:
    day = today_kst()
    records = [_out(r) for r in repo.list_day(db, group_id, day)]
    done = {r.kind for r in records}
    return TodaySummary(date=day, records=records, missing=[k for k in KINDS if k not in done])


# ---- 데일리 체크 ----


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _ensure_sample_items(db: Session, group_id: str) -> None:
    if repo.has_items(db, group_id):
        return
    repo.add_items(
        db,
        [
            CareItem(
                id=uuid.uuid4().hex[:12],
                group_id=group_id,
                name=s["name"],
                mode=s["mode"],
                unit=s.get("unit", ""),
                target=s.get("target"),
                scheduled_time=s["time"],
                meal_type=s.get("meal_type"),
                rule_key=s.get("rule_key"),
                sort_order=i,
            )
            for i, s in enumerate(config.SAMPLE_ITEMS)
        ],
    )


def is_completed(item: CareItem, entry: CareEntry | None) -> bool:
    """예/아니오는 '예', 목표가 있는 수치는 목표 이상, 목표 없는 수치와 컨디션은 기록만 있으면 완료."""
    if entry is None:
        return False
    if item.mode == "yesno":
        return entry.done is True
    if item.mode == "number":
        if entry.number is None:
            return False
        return item.target is None or entry.number >= item.target
    return entry.condition is not None


def is_missing(item: CareItem, completed: bool, day: str, today: str, now_min: int) -> bool:
    """완료되지 않았고 예정 시각 + 60분이 지났으면 누락. 지난 날은 모두 지난 것으로 본다."""
    if completed or day > today:
        return False
    if day < today:
        return True
    return now_min > _minutes(item.scheduled_time) + config.MISSING_GRACE_MINUTES


def _clock(at: str | None) -> tuple[str, int, str]:
    """(오늘, 지금(분), 지금 HH:MM). `at` 이 있으면 그 시각을 지금으로 본다(화면 테스트용)."""
    now = datetime.now(KST)
    if at is not None:
        if not _HHMM.match(at):
            raise bad_request("invalid_time", "시각은 HH:MM 형식이어야 해요")
        return now.date().isoformat(), _minutes(at), at
    return now.date().isoformat(), now.hour * 60 + now.minute, now.strftime("%H:%M")


def _entry_out(e: CareEntry) -> EntryOut:
    return EntryOut(
        done=e.done,
        number=e.number,
        condition=e.condition,
        recorded_by=e.recorded_by,
        recorded_at=e.recorded_at,
    )


def _item_out(it: CareItem, entry: CareEntry | None = None, **flags: bool) -> ItemOut:
    return ItemOut(
        id=it.id,
        name=it.name,
        mode=it.mode,
        unit=it.unit,
        target=it.target,
        scheduled_time=it.scheduled_time,
        meal_type=it.meal_type,
        entry=_entry_out(entry) if entry else None,
        **flags,
    )


def daily(db: Session, group_id: str, day: str | None, at: str | None) -> DailyOut:
    _ensure_sample_items(db, group_id)
    today, now_min, now_text = _clock(at)
    day = day or today
    entries = repo.entries_on(db, group_id, day)
    items: list[ItemOut] = []
    for it in repo.list_items(db, group_id):
        entry = entries.get(it.id)
        completed = is_completed(it, entry)
        items.append(
            _item_out(
                it,
                entry,
                completed=completed,
                missing=is_missing(it, completed, day, today, now_min),
            )
        )
    return DailyOut(
        date=day, now=now_text, items=items, missing_ids=[i.id for i in items if i.missing]
    )


def add_item(db: Session, group_id: str, body: ItemCreate) -> ItemOut:
    _ensure_sample_items(db, group_id)
    if body.mode != "number" and (body.target is not None or body.unit):
        raise bad_request("invalid_item", "목표와 단위는 수치 항목에만 쓸 수 있어요")
    if body.meal_type and body.mode != "yesno":
        raise bad_request("invalid_item", "끼니는 예/아니오 항목에만 지정할 수 있어요")
    item = repo.save_obj(
        db,
        CareItem(
            id=uuid.uuid4().hex[:12],
            group_id=group_id,
            name=body.name.strip(),
            mode=body.mode,
            unit=body.unit.strip(),
            target=body.target,
            scheduled_time=body.scheduled_time,
            meal_type=body.meal_type,
            sort_order=repo.max_sort_order(db, group_id) + 1,
        ),
    )
    return _item_out(item)


def delete_item(db: Session, group_id: str, item_id: str) -> None:
    item = repo.get_item(db, group_id, item_id)
    if item is None:
        raise not_found("항목")
    item.deleted_at = datetime.now(UTC)
    repo.save_obj(db, item)


def put_entry(db: Session, group_id: str, user_id: str, item_id: str, body: EntryPut) -> EntryOut:
    item = repo.get_item(db, group_id, item_id)
    if item is None:
        raise not_found("항목")
    if item.mode == "yesno" and body.done is None:
        raise bad_request("value_required", "예/아니오 항목은 done 값이 필요해요")
    if item.mode == "number" and body.number is None:
        raise bad_request("value_required", "수치 항목은 number 값이 필요해요")
    if item.mode == "condition" and body.condition is None:
        raise bad_request("value_required", "컨디션 항목은 condition 값이 필요해요")
    day = (body.date or datetime.now(KST).date()).isoformat()
    entry = repo.get_entry(db, item.id, day) or CareEntry(
        id=uuid.uuid4().hex[:12], group_id=group_id, item_id=item.id, date=day
    )
    entry.done = body.done if item.mode == "yesno" else None
    entry.number = body.number if item.mode == "number" else None
    entry.condition = body.condition if item.mode == "condition" else None
    entry.recorded_by, entry.recorded_at = user_id, datetime.now(UTC)
    return _entry_out(repo.save_obj(db, entry))


# ---- 추천 ----


def recommend(db: Session, group_id: str, day: str | None) -> RecommendationList:
    """그날 기록을 보고 물·산책·컨디션·영양제 규칙에 맞는 문구를 고른다. 모델을 쓰지 않는다."""
    _ensure_sample_items(db, group_id)
    day = day or today_kst()
    entries = repo.entries_on(db, group_id, day)
    text = config.RECOMMENDATIONS
    found: list[RecommendationOut] = []

    def add(rule: str, item: CareItem, message: str) -> None:
        found.append(RecommendationOut(rule=rule, item_id=item.id, text=message))

    for it in repo.list_items(db, group_id):
        entry = entries.get(it.id)
        if it.rule_key in ("water", "walk"):
            rule = it.rule_key
            if entry is None or entry.number is None:
                add(rule, it, text[f"{rule}_none"])
            elif it.target and entry.number < it.target:
                add(
                    rule,
                    it,
                    text[f"{rule}_low"].format(
                        left=it.target - entry.number, target=it.target, unit=it.unit
                    ),
                )
        elif it.rule_key == "condition":
            if entry is None or entry.condition is None:
                add("condition", it, text["condition_none"])
            elif entry.condition == "bad":
                add("condition", it, text["condition_bad"])
        elif it.rule_key == "supplement" and not is_completed(it, entry):
            add("supplement", it, text["supplement"])
    if not found:
        found.append(RecommendationOut(rule="none", item_id=None, text=text["none"]))
    return RecommendationList(date=day, recommendations=found)


# ---- 식단 추천 ----


def _meal(meal: str, item_id: str | None, index: int) -> MealOut:
    menus = config.MEAL_MENUS[meal]
    i = index % len(menus)
    return MealOut(
        meal=meal,
        label=config.MEAL_LABELS[meal],
        item_id=item_id,
        menu=menus[i],
        index=i,
        next_index=(i + 1) % len(menus),
        total=len(menus),
    )


def meals(db: Session, group_id: str, day: str | None) -> MealList:
    """아침·점심·저녁 중 아직 기록되지 않은 끼니의 첫 메뉴. '아니오'도 기록으로 본다."""
    _ensure_sample_items(db, group_id)
    day = day or today_kst()
    entries = repo.entries_on(db, group_id, day)
    result = [
        _meal(it.meal_type, it.id, 0)
        for it in repo.list_items(db, group_id)
        if it.meal_type in config.MEAL_MENUS and it.id not in entries
    ]
    order = list(config.MEAL_MENUS)
    result.sort(key=lambda m: order.index(m.meal))
    return MealList(date=day, meals=result)


def meal_menu(meal: str, index: int) -> MealOut:
    if meal not in config.MEAL_MENUS:
        raise not_found("끼니")
    return _meal(meal, None, index)


# ---- 위치 공유 ----
# 위치는 개인정보다. 동의한 사람만 보낼 수 있고, 같은 가족 구성원만 볼 수 있으며, 좌표를 로그에 남기지 않고
# 외부 서비스로 보내지 않는다. 동의를 철회하면 저장된 위치를 바로 지운다.


def location_consent(user) -> ConsentOut:
    return ConsentOut(consent=user.location_consent_at is not None, since=user.location_consent_at)


def set_consent(db: Session, user, consent: bool) -> ConsentOut:
    set_location_consent(db, user, consent, source="care")
    if not consent:
        repo.delete_user_locations(db, user.id)
    return location_consent(user)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def save_locations(db: Session, user, batch: LocationBatch) -> LocationSaved:
    """동의한 사람이 기기에서 잰 위치를 보낸다. 너무 오래됐거나 미래 시각인 점은 버린다."""
    if user.location_consent_at is None:
        raise ApiError(403, "consent_required", "위치 공유에 동의해야 위치를 보낼 수 있어요")
    now = datetime.now(UTC)
    oldest = now - timedelta(days=config.LOCATION_RETENTION_DAYS)
    newest = now + timedelta(minutes=config.LOCATION_FUTURE_SKEW_MINUTES)
    rows = [
        CareLocation(
            id=uuid.uuid4().hex[:12],
            user_id=user.id,
            lat=p.lat,
            lng=p.lng,
            accuracy_m=p.accuracy_m,
            recorded_at=_aware(p.recorded_at),
            received_at=now,
        )
        for p in batch.points
        if oldest <= _aware(p.recorded_at) <= newest
    ]
    if rows:
        repo.add_locations(db, rows)
    repo.purge_locations_before(db, oldest)  # 보관 기간이 지난 위치는 쓸 때 함께 지운다
    return LocationSaved(saved=len(rows), skipped=len(batch.points) - len(rows))


def latest_locations(db: Session, group_id: str, user) -> LocationsLatest:
    """가족 구성원의 최신 위치. 동의하지 않은 사람은 좌표 없이 sharing=false 로만 나온다."""
    now = datetime.now(UTC)
    since = now - timedelta(days=config.LOCATION_RETENTION_DAYS)
    members: list[MemberLocation] = []
    for m in group_repo.members(db, group_id):
        sharing = m.location_consent_at is not None
        row = repo.latest_location(db, m.id, since) if sharing else None
        recorded = _aware(row.recorded_at) if row else None
        members.append(
            MemberLocation(
                user_id=m.id,
                name=m.name,
                is_me=m.id == user.id,
                sharing=sharing,
                lat=row.lat if row else None,
                lng=row.lng if row else None,
                accuracy_m=row.accuracy_m if row else None,
                recorded_at=recorded,
                minutes_ago=max(0, int((now - recorded).total_seconds() // 60))
                if recorded
                else None,
            )
        )
    return LocationsLatest(members=members, retention_days=config.LOCATION_RETENTION_DAYS)
