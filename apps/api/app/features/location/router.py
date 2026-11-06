from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import agent, service
from .schemas import (
    AskIn,
    AskOut,
    BackgroundIn,
    ConsentIn,
    FamilyLocations,
    MyLocationOut,
    PauseIn,
    PointIn,
    PointSaved,
    SimulateIn,
)

router = APIRouter(prefix="/location", tags=["location"])


@router.get("/me", response_model=MyLocationOut)
def get_me(user=Depends(current_user), db: Session = Depends(get_db)) -> MyLocationOut:
    """내 위치 공유 상태. 서버 스위치가 꺼져 있어도 읽을 수 있다(앱이 꺼짐 화면을 고르는 데 쓴다)."""
    return service.my_status(db, user)


@router.put("/consent", response_model=MyLocationOut)
def put_consent(
    body: ConsentIn, user=Depends(current_user), db: Session = Depends(get_db)
) -> MyLocationOut:
    """동의(켜기는 스위치가 켜져 있을 때만)와 철회(항상). 철회하면 저장된 내 위치를 모두 지운다."""
    return service.set_consent(db, user, body.consent)


@router.delete("/me", response_model=MyLocationOut)
def delete_me(user=Depends(current_user), db: Session = Depends(get_db)) -> MyLocationOut:
    """저장된 내 위치·활동 구역·설정을 지운다(동의 상태는 그대로)."""
    return service.delete_my_data(db, user)


@router.put("/pause", response_model=MyLocationOut)
def put_pause(
    body: PauseIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MyLocationOut:
    """여행 등으로 위치 공유를 잠시 멈추거나(days 1~14) 다시 켠다(days 없음/0)."""
    return service.set_pause(db, user, group_id, body.days)


@router.post("/points", response_model=PointSaved, status_code=201)
def post_point(
    body: PointIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PointSaved:
    """내 위치 하나를 올린다. 구역 밖이면 부모(관리자)에게 알림이 간다."""
    return service.save_point(db, user, group_id, body)


@router.get("/family", response_model=FamilyLocations)
def get_family(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> FamilyLocations:
    return service.family_locations(db, user, group_id)


@router.post("/simulate-exit", response_model=PointSaved)
def post_simulate_exit(
    body: SimulateIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PointSaved:
    """시연용: 내가 활동 구역을 벗어난 것처럼 판정만 해서 부모에게 알림을 보낸다(위치는 저장하지 않는다)."""
    return service.simulate_exit(db, user, group_id, body.distance_m)


@router.post("/ask", response_model=AskOut)
def post_ask(
    body: AskIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AskOut:
    """위치 기록에 대한 질문에 답한다(부모는 가족 전체, 그 밖의 사람은 본인 기록만). 가족 AI 동의와 하루 한도를 따른다."""
    service.ensure_enabled()
    service.ensure_ask_enabled()
    reply = agent.ask(db, group_id, user, body.question, history=body.history)
    return AskOut(answer=reply.answer, used_tool=bool(reply.tool_calls))


@router.put("/background", response_model=MyLocationOut)
def put_background(
    body: BackgroundIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> MyLocationOut:
    """앱이 꺼져 있어도 위치를 모으는 것에 동의(켜기)하거나 끈다. 켜려면 위치 공유에 먼저 동의해야 한다."""
    return service.set_background(db, user, group_id, body.enabled)
