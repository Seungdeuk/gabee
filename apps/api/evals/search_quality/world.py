"""합성 가족 대화를 앱의 공개 API(TestClient)로 만든다. 임시 SQLite 에서만 쓰고 운영 코드·공용 DB 는 건드리지 않는다.

- 가족 두 곳(요청자 지민의 가족, 이웃 가족)과 가족 전체방·1:1 방 둘을 만들고 `data.MESSAGES` 를 시각순으로 올린다.
- 메시지 id 는 올리는 순서대로 매겨진다(키 -> id 대응표 `World.ids`). gold 는 이 대응표로 관리한다.
- 보낸 시각(`created_at`)은 선언한 한국 시간으로 직접 바꾼다(고정 시계는 날짜를 하루로 묶어 두므로). 앱은 시각으로 정렬하지 않고 id 로 정렬하므로 검색 순서는 같다.
- 지우기: "api" 는 앱의 삭제 API(본문이 비워진다), "flag" 는 본문을 둔 채 `deleted_at` 만 켠다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import update

from app.features.family_chat.models import Message
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

from . import data

KST = timezone(timedelta(hours=9))


@dataclass
class World:
    ids: dict[str, int] = field(default_factory=dict)  # 메시지 키 -> id
    keys: dict[int, str] = field(default_factory=dict)  # id -> 메시지 키
    headers: dict[str, dict] = field(default_factory=dict)
    user_ids: dict[str, str] = field(default_factory=dict)
    rooms: dict[str, str] = field(default_factory=dict)
    group_id: str = ""  # 요청자 가족의 그룹 id
    other_group_id: str = ""

    def key_of(self, message_id: int) -> str:
        return self.keys.get(message_id, f"unknown:{message_id}")


def _me(client: TestClient, headers: dict) -> dict:
    r = client.get("/family-group/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _kst(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d %H:%M").replace(tzinfo=KST).astimezone(UTC)


def build(client: TestClient) -> World:
    """합성 월드를 만든다. 같은 DB 상태에서 만들면 항상 같은 내용·같은 id 다."""
    world = World()
    a = signup(client, data.REQUESTER)
    group = client.post("/family-group/groups", json={"name": data.FAMILY_NAME}, headers=a).json()
    world.group_id = group["id"]
    world.headers[data.REQUESTER] = a
    for name in data.MEMBERS[1:]:
        h = signup(client, name)
        join_family(client, a, group["invite_code"], h)
        world.headers[name] = h
    outsider = signup(client, data.OUTSIDER)
    other = client.post(
        "/family-group/groups", json={"name": data.OTHER_FAMILY_NAME}, headers=outsider
    ).json()
    world.other_group_id = other["id"]
    world.headers[data.OUTSIDER] = outsider
    for name, h in world.headers.items():
        world.user_ids[name] = _me(client, h)["id"]

    rooms = client.get("/family-chat/rooms", headers=a).json()
    world.rooms["family"] = next(r["id"] for r in rooms if r["kind"] == "family")
    other_rooms = client.get("/family-chat/rooms", headers=outsider).json()
    world.rooms["other"] = next(r["id"] for r in other_rooms if r["kind"] == "family")
    for key in ("dm_jm_sh", "dm_sh_ha"):
        opener, peer = data.ROOMS[key]
        r = client.post(
            "/family-chat/rooms/direct",
            json={"user_id": world.user_ids[peer]},
            headers=world.headers[opener],
        )
        assert r.status_code == 200, r.text
        world.rooms[key] = r.json()["id"]

    for msg in data.ordered():
        r = client.post(
            "/family-chat/messages",
            json={"text": msg.text, "room_id": world.rooms[msg.room]},
            headers=world.headers[msg.author],
        )
        assert r.status_code == 201, f"{msg.key} {r.status_code} {r.text}"
        mid = r.json()["id"]
        world.ids[msg.key] = mid
        world.keys[mid] = msg.key
        if msg.deleted == "api":
            gone = client.delete(f"/family-chat/messages/{mid}", headers=world.headers[msg.author])
            assert gone.status_code == 200, gone.text

    with SessionLocal() as db:
        for msg in data.MESSAGES:
            values = {"created_at": _kst(msg.day)}
            if msg.deleted == "flag":
                values["deleted_at"] = _kst(msg.day)
            db.execute(update(Message).where(Message.id == world.ids[msg.key]).values(**values))
        db.commit()
    return world
