"""공동 할 일(family_todos)의 DB 접근. 모든 조회·수정에 group_id 조건을 SQL 에 넣어 다른 가족의 할 일에 닿지 않게 한다."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember

from .models import FamilyTodo

TODO_LIMIT = 300  # 가족 하나당 보관할 수 있는 할 일 수(완료 포함)


def count(db: Session, group_id: str) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(FamilyTodo).where(FamilyTodo.group_id == group_id)
        )
        or 0
    )


def list_todos(db: Session, group_id: str, status: str, limit: int) -> list[FamilyTodo]:
    """open: 기한 빠른 순(기한 없는 것은 뒤), done: 최근에 끝낸 순, all: open 다음 done."""
    stmt = select(FamilyTodo).where(FamilyTodo.group_id == group_id)
    if status == "open":
        stmt = stmt.where(FamilyTodo.done_at.is_(None))
    elif status == "done":
        stmt = stmt.where(FamilyTodo.done_at.is_not(None))
    open_first = case((FamilyTodo.done_at.is_(None), 0), else_=1)
    # 안 끝난 일만 기한 순(기한 없는 것은 뒤)으로 줄 세우고, 끝난 일은 이 두 키가 모두 같아 done_at 최근 순만 남는다
    no_due_last = case(
        (FamilyTodo.done_at.is_(None), case((FamilyTodo.due_date.is_(None), 1), else_=0)), else_=0
    )
    due_first = case((FamilyTodo.done_at.is_(None), FamilyTodo.due_date), else_=None)
    stmt = stmt.order_by(
        open_first,
        no_due_last,
        due_first,
        FamilyTodo.done_at.desc(),
        FamilyTodo.created_at,
        FamilyTodo.id,
    ).limit(limit)
    return list(db.scalars(stmt))


def get(db: Session, group_id: str, todo_id: str) -> FamilyTodo | None:
    return db.scalar(
        select(FamilyTodo).where(FamilyTodo.id == todo_id, FamilyTodo.group_id == group_id)
    )


def add(db: Session, todo: FamilyTodo) -> FamilyTodo:
    db.add(todo)
    db.commit()
    return todo


def save(db: Session, todo: FamilyTodo) -> FamilyTodo:
    db.commit()
    db.refresh(todo)
    return todo


def delete(db: Session, todo: FamilyTodo) -> None:
    db.delete(todo)
    db.commit()


def member_role(db: Session, group_id: str, user_id: str) -> str | None:
    """가족 구성원이면 역할(owner/admin/member), 아니면 None."""
    return db.scalar(
        select(GroupMember.role).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )
