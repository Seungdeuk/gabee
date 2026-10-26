"""공동 할 일: 가족 전체 공유, 담당자는 가족 구성원만, 완료·되돌리기, 지우기 권한, 가족 간 격리, AI 를 부르지 않는다."""

import httpx
import pytest
from sqlalchemy import select

from app.features.family_chat import todo_repository
from app.features.family_chat.models import FamilyTodo
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

TODOS = "/family-chat/todos"


@pytest.fixture(autouse=True)
def _no_ai(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _add(client, headers, title="우유 사 오기", **extra):
    r = client.post(TODOS, json={"title": title, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _titles(client, headers, status="open"):
    r = client.get(TODOS, params={"status": status}, headers=headers)
    assert r.status_code == 200, r.text
    return [t["title"] for t in r.json()]


def test_create_and_everyone_in_the_family_sees_it(client, family):
    a, b, _ = family
    todo = _add(client, a, "  우유   사 오기 ", assignee_id=_uid(client, b), due_date="2026-11-03")
    assert todo["title"] == "우유 사 오기"  # 공백 정리
    assert todo["assignee_id"] == _uid(client, b) and todo["due_date"] == "2026-11-03"
    assert todo["done"] is False and todo["done_at"] is None and todo["source"] == "manual"
    assert todo["created_by"] == _uid(client, a)
    assert _titles(client, b) == ["우유 사 오기"]  # 수진도 본다


def test_created_by_cannot_be_spoofed(client, family):
    a, b, _ = family
    todo = _add(client, a, "내가 만든 것", created_by=_uid(client, b), done_by="x")
    assert todo["created_by"] == _uid(client, a) and todo["done_by"] is None


def test_assignee_must_be_a_family_member(client, family, other_family):
    a, _, _ = family
    stranger = _uid(client, other_family)
    r = client.post(TODOS, json={"title": "x", "assignee_id": stranger}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_member"
    r = client.post(TODOS, json={"title": "x", "assignee_id": "nobody"}, headers=a)
    assert r.status_code == 400
    todo = _add(client, a)
    r = client.patch(f"{TODOS}/{todo['id']}", json={"assignee_id": stranger}, headers=a)
    assert r.status_code == 400
    assert client.get(TODOS, headers=a).json()[0]["assignee_id"] is None  # 바뀌지 않았다


def test_validation(client, family):
    a, _, _ = family
    assert client.post(TODOS, json={"title": ""}, headers=a).status_code == 422
    assert client.post(TODOS, json={"title": "x" * 121}, headers=a).status_code == 422
    r = client.post(TODOS, json={"title": "   "}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_title"
    assert (
        client.post(TODOS, json={"title": "x", "due_date": "2026-13-45"}, headers=a).status_code
        == 422
    )
    assert client.post(TODOS, json={"title": "x", "source": "ai"}, headers=a).status_code == 422
    todo = _add(client, a)
    r = client.patch(f"{TODOS}/{todo['id']}", json={}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "empty_update"
    r = client.patch(f"{TODOS}/{todo['id']}", json={"title": None}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_title"
    r = client.patch(f"{TODOS}/{todo['id']}", json={"done": None}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_done"


def test_complete_and_reopen(client, family):
    a, b, _ = family
    todo = _add(client, a)
    done = client.patch(f"{TODOS}/{todo['id']}", json={"done": True}, headers=b).json()
    assert done["done"] is True and done["done_by"] == _uid(client, b) and done["done_at"]
    assert _titles(client, a) == [] and _titles(client, a, "done") == ["우유 사 오기"]
    again = client.patch(f"{TODOS}/{todo['id']}", json={"done": True}, headers=a).json()
    assert (
        again["done_by"] == _uid(client, b) and again["done_at"] == done["done_at"]
    )  # 다시 완료해도 그대로
    reopened = client.patch(f"{TODOS}/{todo['id']}", json={"done": False}, headers=a).json()
    assert reopened["done"] is False and reopened["done_at"] is None and reopened["done_by"] is None
    assert _titles(client, a) == ["우유 사 오기"]


def test_edit_fields_and_clear_assignee_and_due(client, family):
    a, b, _ = family
    todo = _add(client, a, assignee_id=_uid(client, b), due_date="2026-11-03")
    r = client.patch(
        f"{TODOS}/{todo['id']}",
        json={"title": "두유 사 오기", "assignee_id": None, "due_date": None},
        headers=b,
    )
    body = r.json()
    assert r.status_code == 200 and body["title"] == "두유 사 오기"
    assert body["assignee_id"] is None and body["due_date"] is None
    # 보내지 않은 항목은 그대로
    r = client.patch(f"{TODOS}/{todo['id']}", json={"due_date": "2026-12-01"}, headers=a).json()
    assert r["title"] == "두유 사 오기" and r["due_date"] == "2026-12-01"


def test_list_order_open_by_due_then_no_due_and_status_filter(client, family):
    a, _, _ = family
    _add(client, a, "기한 없음")
    _add(client, a, "늦은 기한", due_date="2026-12-01")
    _add(client, a, "빠른 기한", due_date="2026-11-01")
    done = _add(client, a, "끝낸 일")
    client.patch(f"{TODOS}/{done['id']}", json={"done": True}, headers=a)
    assert _titles(client, a) == ["빠른 기한", "늦은 기한", "기한 없음"]
    assert _titles(client, a, "done") == ["끝낸 일"]
    assert _titles(client, a, "all") == [
        "빠른 기한",
        "늦은 기한",
        "기한 없음",
        "끝낸 일",
    ]  # 안 끝난 것 먼저
    assert len(client.get(TODOS, params={"status": "all", "limit": 2}, headers=a).json()) == 2
    assert client.get(TODOS, params={"status": "bogus"}, headers=a).status_code == 422
    assert client.get(TODOS, params={"limit": 0}, headers=a).status_code == 422


def test_other_family_cannot_see_or_touch(client, family, other_family):
    a, _, _ = family
    todo = _add(client, a)
    assert client.get(TODOS, headers=other_family).json() == []
    assert (
        client.patch(f"{TODOS}/{todo['id']}", json={"done": True}, headers=other_family).status_code
        == 404
    )
    assert client.delete(f"{TODOS}/{todo['id']}", headers=other_family).status_code == 404
    assert _titles(client, a) == ["우유 사 오기"]  # 그대로
    assert client.patch(f"{TODOS}/nonexistent", json={"done": True}, headers=a).status_code == 404


def test_delete_permission_creator_or_manager(client, trio_family):
    owner, member, other_member = trio_family
    mine = _add(client, member, "수진이 만든 것")
    owners = _add(client, owner, "지민이 만든 것")
    # 만든 사람이 아닌 일반 구성원은 못 지운다
    r = client.delete(f"{TODOS}/{owners['id']}", headers=member)
    assert r.status_code == 403 and r.json()["code"] == "not_allowed"
    assert client.delete(f"{TODOS}/{mine['id']}", headers=other_member).status_code == 403
    # 만든 사람은 지울 수 있다
    assert client.delete(f"{TODOS}/{mine['id']}", headers=member).status_code == 204
    # 가족 관리자(소유자)는 남이 만든 것도 지울 수 있다
    again = _add(client, member, "다시 만든 것")
    assert client.delete(f"{TODOS}/{again['id']}", headers=owner).status_code == 204
    assert _titles(client, owner) == ["지민이 만든 것"]
    # 일반 구성원도 완료·수정은 할 수 있다(공유)
    assert (
        client.patch(
            f"{TODOS}/{owners['id']}", json={"done": True}, headers=other_member
        ).status_code
        == 200
    )


@pytest.fixture
def trio_family(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    r = join_family(client, a, group["invite_code"], c)
    assert r.status_code == 200
    return a, b, c  # 지민(소유자), 수진, 삼촌(일반 구성원)


def test_limit_per_family(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(todo_repository, "TODO_LIMIT", 3)
    for i in range(3):
        _add(client, a, f"일 {i}")
    r = client.post(TODOS, json={"title": "넘침"}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "todo_limit"


def test_source_chat_is_recorded(client, family):
    a, _, _ = family
    assert _add(client, a, "AI 후보를 확인해 등록", source="chat")["source"] == "chat"
    with SessionLocal() as db:
        assert db.scalars(select(FamilyTodo)).one().source == "chat"


def test_requires_login_and_group(client, family):
    assert client.get(TODOS).status_code == 401
    assert client.post(TODOS, json={"title": "x"}).status_code == 401
    lonely = signup(client, "혼자")
    r = client.get(TODOS, headers=lonely)
    assert r.status_code == 400 and r.json()["code"] == "no_group"


def test_done_list_is_most_recently_finished_first_regardless_of_due_date(client, family):
    a, _, _ = family
    old = _add(client, a, "먼저 끝냄", due_date="2026-01-01")
    new = _add(client, a, "나중에 끝냄")  # 기한 없음
    mid = _add(client, a, "중간에 끝냄", due_date="2026-12-31")
    for t in (old, mid, new):  # 완료 순서: old → mid → new
        client.patch(f"{TODOS}/{t['id']}", json={"done": True}, headers=a)
    assert _titles(client, a, "done") == ["나중에 끝냄", "중간에 끝냄", "먼저 끝냄"]
    _add(client, a, "안 끝남")
    assert _titles(client, a, "all")[0] == "안 끝남"  # 안 끝난 것이 먼저, 그다음 끝난 것은 최근 순
    assert _titles(client, a, "all")[1:] == ["나중에 끝냄", "중간에 끝냄", "먼저 끝냄"]
    assert _titles(client, a, "done")[:1] == ["나중에 끝냄"]
    assert len(client.get(TODOS, params={"status": "done", "limit": 1}, headers=a).json()) == 1
