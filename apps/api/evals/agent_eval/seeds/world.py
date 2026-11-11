"""합성 가족 월드를 앱의 공개 API(TestClient)로 만든다. 운영 코드·공용 DB·환경변수는 건드리지 않는다.

- `build_legacy`: 기존 정산 52건이 쓰는 시드(`evals/tab_agents/seed.py`)를 기존 실행기와 같은 순서·이름으로 만든다. 기존 사례의 기대값이
  그대로 맞도록 이 부분은 바꾸지 않는다.
- `build_world`: 그 위에 가족방·1:1·일정·할 일·부탁·습관 데이터(`data.py` 의 선언)를 더한다. 같은 DB 상태에서 만들면 항상 같은 내용이다.
- 날짜가 고정된 안에서만, 그것도 기준 날짜(`data.REFERENCE_DAY`)로 고정한 시계 안에서만 만든다(`eval_process`/`frozen_clock`). 서버가 "오늘"을
  읽어 정하는 값(습관 기록 날짜 등)과 대화 속 "내일"·일정 날짜가 어긋나지 않게 한다.
- 만드는 것은 앱의 공개 API 로 하되, 가족 AI 동의 켜기(`ai_guard.set_enabled`)와 구성원 id 조회는 `SessionLocal` 로 직접 한다(공개 API 가 아님).
- 기존 정산 52건은 `build_legacy` 를 기준으로 한다(기존 실행기와 같다). `build_world` 위에서의 결과는 메인 도구(`ask_family_chat`·`ask_schedule`)가
  새 데이터를 건드릴 수 있어 L2 실행(E4c)에서 따로 확인한다. `build_legacy` 는 기존 실행기처럼 AI 동의를 켜지 않고 `build_world` 는 두 가족 모두 켠다.
"""

from dataclasses import dataclass, field
from datetime import timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.features.family_group.models import User
from app.shared import ai_guard
from app.shared.db import SessionLocal
from evals.agent_eval.clock import reference_now
from evals.tab_agents import seed as legacy
from tests.helpers import join_family, signup

from . import data


@dataclass
class Member:
    name: str
    headers: dict
    user_id: str
    group_id: str


@dataclass
class World:
    members: dict[str, Member] = field(default_factory=dict)
    rooms: dict[str, str] = field(default_factory=dict)  # data.ROOM_MEMBERS 의 방 키 -> 방 id
    # 만든 항목의 id: 수정·삭제 대상을 제목으로 다시 찾지 않게 한다. 키는 (소유자·보낸 사람, 제목)
    events: dict[tuple[str, str], str] = field(default_factory=dict)
    todos: dict[tuple[str, str], str] = field(default_factory=dict)
    requests: dict[tuple[str, str], str] = field(default_factory=dict)
    habits: dict[tuple[str, str], str] = field(default_factory=dict)

    def headers(self, name: str) -> dict:
        return self.members[name].headers

    def id_of(self, name: str) -> str:
        return self.members[name].user_id


def _member(client: TestClient, name: str, headers: dict) -> Member:
    me = client.get("/family-group/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    return Member(name, headers, body["id"], body.get("active_group_id") or "")


def _require_frozen_clock() -> None:
    ref = reference_now()
    if ref is None:
        raise RuntimeError("합성 월드는 고정 시계 안에서만 만든다(eval_process 또는 frozen_clock)")
    day = ref.astimezone(timezone(timedelta(hours=9))).date().isoformat()
    if day != data.REFERENCE_DAY:
        raise RuntimeError(
            f"시계가 기준 날짜({data.REFERENCE_DAY})가 아니라 {day} 로 고정되어 있다"
        )
    from app.shared.db import engine

    if engine.url.get_backend_name() != "sqlite":
        raise RuntimeError(
            "합성 월드는 임시 SQLite 에서만 만든다(env.check_process_boundary 를 먼저 통과해야 한다)"
        )


def build_legacy(client: TestClient) -> World:
    """기존 정산 시드: 지민·수진·민수(같은 가족)와 남(다른 가족). 기존 실행기와 같은 순서다."""
    _require_frozen_clock()
    a = signup(client, "지민")
    group = client.post("/family-group/groups", json={"name": data.FAMILY_NAME}, headers=a).json()
    b = signup(client, "수진")
    join_family(client, a, group["invite_code"], b)
    legacy.seed(client, a, b)
    child = signup(client, "민수", "child")
    join_family(client, a, group["invite_code"], child)
    with SessionLocal() as db:
        child_id = db.scalars(select(User).where(User.name == "민수")).first().id
    legacy.seed_child(client, a, child_id)
    legacy.seed_write_targets(client, a, b, child)
    outsider = signup(client, data.OUTSIDER)
    legacy.seed_other_family(client, outsider)
    world = World()
    for name, headers in (("지민", a), ("수진", b), ("민수", child), (data.OUTSIDER, outsider)):
        world.members[name] = _member(client, name, headers)
    return world


def _post(client: TestClient, path: str, headers: dict, body: dict, status: int = 201) -> dict:
    r = client.post(path, json=body, headers=headers)
    assert r.status_code == status, f"{path} {r.status_code} {r.text}"
    return r.json()


def _open_rooms(client: TestClient, world: World) -> None:
    """가족 전체방 id 와 지민이 여는 1:1 방들, 다른 가족의 전체방 id 를 찾는다."""
    a = world.headers("지민")
    rooms = client.get("/family-chat/rooms", headers=a).json()
    world.rooms["family"] = next(r["id"] for r in rooms if r["kind"] == "family")
    world.rooms["ab"] = _post(
        client, "/family-chat/rooms/direct", a, {"user_id": world.id_of("수진")}, 200
    )["id"]
    world.rooms["ac"] = _post(
        client, "/family-chat/rooms/direct", a, {"user_id": world.id_of("민수")}, 200
    )["id"]
    other = client.get("/family-chat/rooms", headers=world.headers(data.OUTSIDER)).json()
    world.rooms["other"] = next(r["id"] for r in other if r["kind"] == "family")


def _chat(client: TestClient, world: World) -> None:
    for m in data.MESSAGES:
        _post(
            client,
            "/family-chat/messages",
            world.headers(m.author),
            {"text": m.text, "room_id": world.rooms[m.room]},
        )


def _schedule(client: TestClient, world: World) -> None:
    for e in data.EVENTS:
        body = {
            "title": e.title,
            "start_date": e.day,
            "start_time": e.start,
            "end_time": e.end,
            "place": e.place,
            "memo": e.memo or None,
            "status": e.status,
            "source": e.source,
            "kind": e.kind,
            "share_with": [world.id_of(n) for n in e.share_with],
        }
        created = _post(client, "/schedule/events", world.headers(e.owner), body)
        world.events[(e.owner, e.title)] = created["id"]
    for r in data.REQUESTS:
        created = _post(
            client,
            "/schedule/requests",
            world.headers(r.sender),
            {
                "title": r.title,
                "start_date": r.day,
                "place": r.place,
                "memo": r.memo,
                "to_ids": [world.id_of(n) for n in r.recipients],
            },
        )
        world.requests[(r.sender, r.title)] = created["id"]
    for h in data.HABITS:
        headers = world.headers(h.owner)
        item = _post(
            client,
            "/schedule/check/items",
            headers,
            {
                "name": h.name,
                "kind": h.kind,
                "goal": h.goal,
                "unit": h.unit,
                "shared": h.shared,
            },
        )
        world.habits[(h.owner, h.name)] = item["id"]
        entry = {k: v for k, v in (("count", h.count), ("done", h.done)) if v is not None}
        if entry:
            r = client.put(f"/schedule/check/items/{item['id']}/entry", json=entry, headers=headers)
            assert r.status_code == 200, r.text


def _todos(client: TestClient, world: World) -> None:
    for t in data.TODOS:
        created = _post(
            client,
            "/family-chat/todos",
            world.headers(t.creator),
            {
                "title": t.title,
                "assignee_id": world.id_of(t.assignee) if t.assignee else None,
                "due_date": t.due,
                "source": t.source,
            },
        )
        world.todos[(t.creator, t.title)] = created["id"]


def enable_ai(world: World) -> None:
    """두 가족 모두 AI 동의를 켠다(소유자·관리자가 앱에서 켠 것과 같은 결과). 공개 API 가 아니라 DB 에 직접 쓴다."""
    with SessionLocal() as db:
        for owner in ("지민", data.OUTSIDER):
            m = world.members[owner]
            ai_guard.set_enabled(db, m.group_id, m.user_id, True)


def build_world(client: TestClient) -> World:
    """기존 정산 시드 위에 가족방·1:1·일정·할 일·부탁·습관을 더한 합성 가족 월드."""
    world = build_legacy(client)
    _open_rooms(client, world)
    _chat(client, world)
    _schedule(client, world)
    _todos(client, world)
    enable_ai(world)
    return world
