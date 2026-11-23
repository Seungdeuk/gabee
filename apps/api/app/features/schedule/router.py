from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import (
    chat_share,  # noqa: F401  (import 하면 공유 카드의 일정 내용 만들기가 등록된다)
    news_source,  # noqa: F401  (import 하면 주간 뉴스의 일정 재료 읽기가 등록된다)
    service,
)
from . import together as request_service
from .agent.router import router as agent_router
from .check_router import router as check_router
from .models import Event, EventTopic
from .schemas import (
    CheckBody,
    EventCreate,
    EventOut,
    EventUpdate,
    RequestAnswer,
    RequestCreate,
    RequestMemo,
    RequestOut,
    RequestRecipients,
    SharingOut,
    TopicCreate,
    TopicOut,
)

router = APIRouter(prefix="/schedule", tags=["schedule"])
router.include_router(agent_router)


@router.get("/events", response_model=list[EventOut])
def list_events(
    include_past: bool = False,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[Event]:
    return service.upcoming(db, group_id, user.id, include_past)


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(
    body: EventCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.create(db, group_id, user.id, body)


@router.post("/events/{event_id}/confirm", response_model=EventOut)
def confirm_event(
    event_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.confirm(db, group_id, user.id, event_id)


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    body: EventUpdate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.update(db, group_id, user.id, event_id, body)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    service.remove(db, group_id, user.id, event_id)
    return Response(status_code=204)


@router.put("/events/{event_id}/checked", response_model=EventOut)
def set_event_checked(
    event_id: str,
    body: CheckBody,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Event:
    return service.set_checked(db, group_id, user.id, event_id, body.checked)


@router.get("/events/{event_id}/sharing", response_model=SharingOut)
def event_sharing(
    event_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return service.sharing(db, group_id, user.id, event_id)


@router.get("/topics", response_model=list[TopicOut])
def list_topics(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[EventTopic]:
    return service.list_topics(db, group_id, user.id)


@router.post("/topics", response_model=TopicOut, status_code=201)
def create_topic(
    body: TopicCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> EventTopic:
    return service.create_topic(db, group_id, user.id, body)


@router.delete("/topics/{topic_id}", status_code=204)
def delete_topic(
    topic_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    service.remove_topic(db, group_id, user.id, topic_id)
    return Response(status_code=204)


@router.post("/requests", response_model=RequestOut, status_code=201)
def create_request(
    body: RequestCreate,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return request_service.create(db, group_id, user.id, body)


@router.get("/requests", response_model=list[RequestOut])
def list_requests(
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    return request_service.list_mine(db, group_id, user.id)


@router.post("/requests/{request_id}/answer", response_model=RequestOut)
def answer_request(
    request_id: str,
    body: RequestAnswer,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return request_service.answer(db, group_id, user.id, request_id, body)


@router.put("/requests/{request_id}/recipients", response_model=RequestOut)
def change_request_recipients(
    request_id: str,
    body: RequestRecipients,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return request_service.change_recipients(db, group_id, user.id, request_id, body)


@router.put("/requests/{request_id}/memo", response_model=RequestOut)
def change_request_memo(
    request_id: str,
    body: RequestMemo,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return request_service.change_memo(db, group_id, user.id, request_id, body.memo)


@router.post("/requests/{request_id}/cancel", response_model=RequestOut)
def cancel_request(
    request_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> dict:
    return request_service.cancel(db, group_id, user.id, request_id)


# 데일리 체크: /schedule/check/... (맨 뒤에 붙여 기존 일정 API 의 문서 순서를 바꾸지 않는다)
router.include_router(check_router)
