from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import service
from .schemas import (
    ConsentOut,
    ConsentSet,
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
    PutResult,
    RecommendationList,
    RecordOut,
    RecordPut,
    TodaySummary,
)

router = APIRouter(prefix="/care", tags=["care"])


@router.put("/records", response_model=PutResult)
def put_record(
    body: RecordPut,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PutResult:
    """같은 날 같은 종류의 기록이 있으면 덮어쓴다."""
    return service.put(db, group_id, user.id, body)


@router.get("/records", response_model=list[RecordOut])
def list_records(
    date: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[RecordOut]:
    return service.list_day(db, group_id, date)


@router.get("/summary/today", response_model=TodaySummary)
def summary_today(
    group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> TodaySummary:
    return service.today_summary(db, group_id)


@router.get("/daily", response_model=DailyOut)
def daily(
    date: str | None = None,
    at: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> DailyOut:
    """데일리 체크 항목과 그날 기록, 누락 여부. `at`(HH:MM)은 화면 테스트용으로 '지금' 시각을 바꾼다."""
    return service.daily(db, group_id, date, at)


@router.post("/items", response_model=ItemOut, status_code=201)
def add_item(
    body: ItemCreate, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> ItemOut:
    return service.add_item(db, group_id, body)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """소프트 삭제: 항목은 목록에서 빠지고 지난 기록은 남는다."""
    service.delete_item(db, group_id, item_id)
    return Response(status_code=204)


@router.put("/items/{item_id}/entry", response_model=EntryOut)
def put_entry(
    item_id: str,
    body: EntryPut,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> EntryOut:
    """항목의 하루 기록. 같은 날 다시 보내면 덮어쓴다."""
    return service.put_entry(db, group_id, user.id, item_id, body)


@router.delete("/items/{item_id}/entry", status_code=204)
def delete_entry(
    item_id: str,
    date: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    """오늘(또는 date)의 기록·건너뛰기를 지워 되돌린다."""
    service.delete_entry(db, group_id, item_id, date)
    return Response(status_code=204)


@router.get("/recommendations", response_model=RecommendationList)
def recommendations(
    date: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> RecommendationList:
    return service.recommend(db, group_id, date)


@router.get("/meals", response_model=MealList)
def meals(
    date: str | None = None,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MealList:
    return service.meals(db, group_id, date)


@router.get("/meals/{meal}", response_model=MealOut)
def meal_menu(meal: str, index: int = 0, _: str = Depends(current_group_id)) -> MealOut:
    """'다른 메뉴': 직전 응답의 `next_index` 를 `index` 로 보내면 다음 메뉴가 나온다."""
    return service.meal_menu(meal, index)


@router.get("/location/consent", response_model=ConsentOut)
def get_location_consent(user=Depends(current_user)) -> ConsentOut:
    """내 위치 공유 동의 상태."""
    return service.location_consent(user)


@router.put("/location/consent", response_model=ConsentOut)
def put_location_consent(
    body: ConsentSet, user=Depends(current_user), db: Session = Depends(get_db)
) -> ConsentOut:
    """위치 공유에 동의하거나 철회한다. 철회하면 저장된 내 위치를 바로 지운다."""
    return service.set_consent(db, user, body.consent)


@router.post("/locations", response_model=LocationSaved, status_code=201)
def post_locations(
    body: LocationBatch,
    user=Depends(current_user),
    _: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LocationSaved:
    """동의한 사람이 위치를 보낸다(앱이 주기적으로 보낸다). 동의하지 않았으면 403 consent_required."""
    return service.save_locations(db, user, body)


@router.get("/locations/latest", response_model=LocationsLatest)
def locations_latest(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> LocationsLatest:
    """가족 구성원의 최신 위치. 동의한 구성원의 위치만 좌표가 내려간다."""
    return service.latest_locations(db, group_id, user)
