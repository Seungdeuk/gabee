"""공동 할 일 엔드포인트. family_chat 라우터에 포함되어 /family-chat/todos 아래로 열린다. 모두 로그인과 가족 구성원 확인이 필요하다.
가족 전체가 공유하고, AI 를 부르지 않는다."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import todo_service
from .schemas import TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/todos")


@router.get("", response_model=list[TodoOut])
def list_todos(
    status: Literal["open", "done", "all"] = Query("open"),
    limit: int = Query(100, ge=1, le=200),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[TodoOut]:
    return todo_service.list_todos(db, group_id, status, limit)


@router.post("", response_model=TodoOut, status_code=201)
def create_todo(
    body: TodoCreate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> TodoOut:
    return todo_service.create(db, user, group_id, body)


@router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: str,
    body: TodoUpdate,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> TodoOut:
    return todo_service.update(db, user, group_id, todo_id, body)


@router.delete("/{todo_id}", status_code=204)
def delete_todo(
    todo_id: str,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> Response:
    todo_service.delete(db, user, group_id, todo_id)
    return Response(status_code=204)
