"""공동 할 일 업무 규칙. 가족 전체가 보고 고치고 완료할 수 있다. 지우는 것은 만든 사람이나 가족 관리자(owner/admin)만 한다.
AI 를 부르지 않는다(AI 가 뽑은 후보는 사용자가 확인해서 누르면 source=chat 으로 여기에 등록된다)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found

from . import todo_repository as repo
from .models import FamilyTodo
from .schemas import TodoCreate, TodoOut, TodoUpdate

MANAGER_ROLES = ("owner", "admin")


def _out(t: FamilyTodo) -> TodoOut:
    return TodoOut(
        id=t.id,
        title=t.title,
        assignee_id=t.assignee_id,
        due_date=t.due_date,
        done=t.done_at is not None,
        done_at=t.done_at,
        done_by=t.done_by,
        created_by=t.created_by,
        source=t.source,
        created_at=t.created_at,
    )


def _title(value: str) -> str:
    title = " ".join(value.split())
    if not title:
        raise bad_request("invalid_title", "할 일 제목을 적어 주세요")
    return title


def _check_assignee(db: Session, group_id: str, assignee_id: str | None) -> None:
    if assignee_id is not None and repo.member_role(db, group_id, assignee_id) is None:
        raise bad_request("invalid_member", "같은 가족 구성원만 담당자로 정할 수 있어요")


def list_todos(db: Session, group_id: str, status: str, limit: int) -> list[TodoOut]:
    return [_out(t) for t in repo.list_todos(db, group_id, status, limit)]


def create(db: Session, user: User, group_id: str, body: TodoCreate) -> TodoOut:
    title = _title(body.title)
    _check_assignee(db, group_id, body.assignee_id)
    if repo.count(db, group_id) >= repo.TODO_LIMIT:
        raise bad_request("todo_limit", "할 일이 너무 많아요. 끝난 할 일을 정리해 주세요")
    now = datetime.now(UTC)
    todo = FamilyTodo(
        group_id=group_id,
        title=title,
        assignee_id=body.assignee_id,
        due_date=body.due_date,
        created_by=user.id,
        source=body.source,
        created_at=now,
        updated_at=now,
    )
    return _out(repo.add(db, todo))


def update(db: Session, user: User, group_id: str, todo_id: str, body: TodoUpdate) -> TodoOut:
    todo = repo.get(db, group_id, todo_id)
    if todo is None:
        raise not_found("할 일")
    sent = body.model_fields_set
    if not sent:
        raise bad_request("empty_update", "바꿀 내용이 없어요")
    if "title" in sent:
        if body.title is None:
            raise bad_request("invalid_title", "할 일 제목을 적어 주세요")
        todo.title = _title(body.title)
    if "assignee_id" in sent:
        _check_assignee(db, group_id, body.assignee_id)
        todo.assignee_id = body.assignee_id
    if "due_date" in sent:
        todo.due_date = body.due_date
    if "done" in sent and body.done is None:
        raise bad_request("invalid_done", "완료 여부는 true 나 false 로 보내 주세요")
    if "done" in sent:
        if body.done and todo.done_at is None:
            todo.done_at, todo.done_by = datetime.now(UTC), user.id
        elif not body.done:
            todo.done_at = todo.done_by = None
    todo.updated_at = datetime.now(UTC)
    return _out(repo.save(db, todo))


def delete(db: Session, user: User, group_id: str, todo_id: str) -> None:
    todo = repo.get(db, group_id, todo_id)
    if todo is None:
        raise not_found("할 일")
    if todo.created_by != user.id and repo.member_role(db, group_id, user.id) not in MANAGER_ROLES:
        raise ApiError(403, "not_allowed", "만든 사람이나 가족 관리자만 지울 수 있어요")
    repo.delete(db, todo)
