"""시드가 만든 월드를 공개 API 로 읽어 본다. 권한 검증·초기화 후 재시드 동일성 비교·E5 의 정보 노출 평가가 같이 쓴다.

읽는 것은 각 사용자가 API 로 실제 볼 수 있는 것뿐이다(그 사용자의 헤더로 조회한다). 비교용 스냅샷은 id 대신 이름·내용만 담아서 다시 만들어도 같다.

노출 기준(`leaks`·`raw_leaks`)의 한계: 누가 무엇을 볼 수 있는지의 선언(`data.py` 의 `visible_to`)은 시드가 보낸 방·`share_with` 와 같은 곳에서 나온다. 선언 자체가
틀리면(예: 일정을 잘못 공유) 이 기준도 같이 틀린다. 앱이 공유 범위를 실제로 집행하는지는 시험의 고정 기대(`test_seeds_world.py` 의 하드코딩 assert)가 따로 본다.
"""

from fastapi.testclient import TestClient

from . import data
from .world import World

LIMIT = 200
SEARCH_TERMS = (
    "비밀",
    "이웃",
    "시계",
    "용돈",
    "치과",
    "상담",
    "캠핑",
)  # 검색 API 로 새는지 보는 낱말


def _get(client: TestClient, path: str, headers: dict, **params):
    return client.get(path, headers=headers, params=params or None)


def room_status(client: TestClient, world: World, user: str, room_key: str) -> int:
    """`user` 가 그 방의 메시지를 읽으려 할 때의 상태 코드(볼 수 없는 방은 404 여야 한다)."""
    r = _get(
        client,
        "/family-chat/messages",
        world.headers(user),
        room_id=world.rooms[room_key],
        limit=LIMIT,
    )
    return r.status_code


def access_matrix(client: TestClient, world: World) -> dict[str, dict[str, int]]:
    """{사용자: {방 키: 상태 코드}}. 방 권한이 같은지 비교할 때 쓴다."""
    return {
        user: {room: room_status(client, world, user, room) for room in data.ROOM_MEMBERS}
        for user in data.ALL_USERS
    }


def reachable_habits(client: TestClient, world: World, user: str) -> list[str]:
    """`user` 가 볼 수 있는 습관 이름: 내 습관과, 같은 가족 구성원의 오늘 현황에 나오는 습관."""
    names = [h["name"] for h in _get(client, "/schedule/check/items", world.headers(user)).json()]
    for member in world.members.values():
        if member.name == user:
            continue
        r = _get(client, f"/schedule/check/members/{member.user_id}/today", world.headers(user))
        if r.status_code == 200:
            names += [i["name"] for i in r.json()["items"]]
    return names


def reachable_texts(client: TestClient, world: World, user: str) -> list[str]:
    """`user` 가 API 로 읽을 수 있는 글(메시지·일정 제목·할 일·부탁 제목·습관 이름)."""
    headers = world.headers(user)
    texts: list[str] = []
    for room in _get(client, "/family-chat/rooms", headers).json():
        r = _get(client, "/family-chat/messages", headers, room_id=room["id"], limit=LIMIT)
        texts += [m["text"] for m in r.json()]
    events = _get(client, "/schedule/events", headers, include_past=True).json()
    texts += [e["title"] for e in events]
    # 장소·메모도 읽힌 글이다: 일정의 비공개 전용 식별값(`EventSpec.private_ids`)이 소유자 밖에 읽히는지 본다
    texts += [e[key] for e in events for key in ("place", "memo") if e.get(key)]
    texts += [t["title"] for t in _get(client, "/family-chat/todos", headers).json()]
    texts += [r["title"] for r in _get(client, "/schedule/requests", headers).json()]
    texts += reachable_habits(client, world, user)
    texts += reachable_docs(client, world, user)
    declared = {
        x.title for x in data.EXPENSES
    }  # 기존 정산 시드의 제목('치과 진료' 등)은 일정 제목과 겹쳐 비교가 흐려지므로 뺀다
    texts += [
        e["title"]
        for month in EXPENSE_MONTHS
        for e in _expenses(client, headers, month)
        if e["title"] in declared
    ]
    return texts


EXPENSE_MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11")


def _expenses(client: TestClient, headers: dict, month: str) -> list[dict]:
    r = _get(client, "/billing/expenses", headers, month=month)
    return r.json() if r.status_code == 200 else []


def reachable_docs(client: TestClient, world: World, user: str) -> list[str]:
    """`user` 가 문서함 API 로 읽을 수 있는 글: 기록 제목과 본문(본문을 열면 읽음 표시가 남는다)."""
    headers = world.headers(user)
    out: list[str] = []
    for item in _get(client, "/ai-assistant/knowledge/items", headers, limit=200).json():
        out.append(item["title"])
        detail = _get(client, f"/ai-assistant/knowledge/items/{item['id']}", headers)
        out.append(detail.json()["body_md"])
    return out


def tool_texts(world: World, user: str) -> list[str]:
    """Agent 의 문서 검색 도구(`search_knowledge`·`list_items`·`get_item`)가 `user` 의 가족 그룹에서 돌려주는 글(제목·본문 조각·전체 글).

    도구는 LLM 없이 부르고, 임베딩 모델이 없으면 해시 임베딩으로 찾는다. 문서 전체 목록(`list_items`)의 모든 기록을 `get_item` 으로 열고,
    선언한 문서 제목마다 제목 낱말로 `search_knowledge` 도 부른다(도구 경로가 API 경로와 같은 경계를 지키는지 본다).
    """
    from app.features.ai_assistant.knowledge import tools
    from app.shared.db import SessionLocal

    group_id = world.members[user].group_id
    out: list[str] = []
    with SessionLocal() as db:
        listed = tools.list_items(db, group_id, limit=50)["items"]
        out += [i["title"] for i in listed]
        for i in listed:
            out.append(tools.get_item(db, group_id, i["item_id"])["text"])
        for d in data.DOCS:
            for r in tools.search_knowledge(db, group_id, d.title, top_k=20)["results"]:
                out += [r["title"], r["text"], *(m["text"] for m in r.get("more", []))]
    return out


def leaks(client: TestClient, world: World) -> list[tuple[str, str]]:
    """(사용자, 표식) 중 보면 안 되는데 API 로 읽히는 것, 그리고 봐야 하는데 안 읽히는 것.

    표식 글 전체는 같은 글인지(==)로, 짧은 낱말 표식(`data.TOKENS`)은 읽힌 글 안에 들어 있는지로 본다.
    """
    problems = []
    for user in data.ALL_USERS:
        seen = reachable_texts(client, world, user)
        for marker in data.MARKERS:
            if (marker.text in seen) != (user in marker.visible_to):
                problems.append((user, marker.text))
        for token in data.TOKENS:
            if any(token.text in t for t in seen) != (user in token.visible_to):
                problems.append((user, token.text))
    return problems


def _billing_titles(client: TestClient, world: World, user: str) -> tuple[str, ...]:
    """그 사람이 정당하게 보는 기존 정산 시드의 지출 제목(금지 문자열에서 빼는 데 쓴다)."""
    titles: list[str] = []
    for month in EXPENSE_MONTHS:
        titles += [e["title"] for e in _expenses(client, world.headers(user), month)]
    return tuple(titles)


def raw_leaks(client: TestClient, world: World) -> list[tuple[str, str, str]]:
    """(사용자, 조회, 금지 문자열): 목록 API 뿐 아니라 방 목록의 마지막 메시지·읽음 상태·검색·공유 현황·습관 현황·그룹 정보까지
    응답 본문 전체에서 그 사람이 볼 수 없는 표식(`data.forbidden_strings`)이 나오는 곳."""
    found = []
    for user in data.ALL_USERS:
        headers = world.headers(user)
        forbidden = data.forbidden_strings(user, also_visible=_billing_titles(client, world, user))
        others = [m.user_id for m in world.members.values() if m.name != user]
        queries = [
            ("rooms", "/family-chat/rooms", {}),
            ("unread", "/family-chat/unread", {}),
            ("read-states", "/family-chat/read-states", {}),
            ("events", "/schedule/events", {"include_past": True}),
            ("todos", "/family-chat/todos", {}),
            ("requests", "/schedule/requests", {}),
            ("habits", "/schedule/check/items", {}),
            ("habit summary", "/schedule/check/members/summary", {}),
            ("group", "/family-group/groups/me", {}),
            ("knowledge", "/ai-assistant/knowledge/items", {"limit": LIMIT}),
        ]
        queries += [(f"expenses {m}", "/billing/expenses", {"month": m}) for m in EXPENSE_MONTHS]
        queries += [
            (f"doc {i[:4]}", f"/ai-assistant/knowledge/items/{i}", {}) for i in world.docs.values()
        ]
        queries += [(f"today {i[:4]}", f"/schedule/check/members/{i}/today", {}) for i in others]
        queries += [
            (f"sharing {i[:4]}", f"/schedule/events/{i}/sharing", {}) for i in world.events.values()
        ]
        queries += [(f"search {q}", "/family-chat/search", {"q": q}) for q in SEARCH_TERMS]
        queries += [
            (f"messages {room}", "/family-chat/messages", {"room_id": rid, "limit": LIMIT})
            for room, rid in world.rooms.items()
        ]
        for label, path, params in queries:
            body = _get(client, path, headers, **params).text
            found += [(user, label, s) for s in forbidden if s in body]
    return found


def extra_access(client: TestClient, world: World) -> dict[str, int]:
    """쓰기·검색·읽음 상태·공유 현황·구성원 현황에서 막혀야 하는 요청의 상태 코드(모두 404 여야 한다)."""
    ab = world.rooms["ab"]
    dental = world.events[("지민", "치과 진료")]
    jimin = world.id_of("지민")
    outsider, minsu = world.headers(data.OUTSIDER), world.headers("민수")
    return {
        "민수가 지민-수진 방에 글쓰기": client.post(
            "/family-chat/messages", json={"text": "끼어들기", "room_id": ab}, headers=minsu
        ).status_code,
        "민수가 지민-수진 방 검색": _get(
            client, "/family-chat/search", minsu, q="비밀", room_id=ab
        ).status_code,
        "민수가 지민-수진 방 읽음 상태": _get(
            client, "/family-chat/read-states", minsu, room_id=ab
        ).status_code,
        "민수가 지민-수진 방 안 읽은 수": _get(
            client, "/family-chat/unread", minsu, room_id=ab
        ).status_code,
        "남이 지민의 습관 현황": _get(
            client, f"/schedule/check/members/{jimin}/today", outsider
        ).status_code,
        "남이 지민 일정의 공유 현황": _get(
            client, f"/schedule/events/{dental}/sharing", outsider
        ).status_code,
    }


def stored_texts(client: TestClient, world: World) -> set[str]:
    """모든 사용자가 읽을 수 있는 서버에 저장된 글의 합집합(선언되지 않은 값이 저장됐는지 볼 때 쓴다).

    제목뿐 아니라 일정의 장소·메모, 부탁의 장소·메모, 습관 이름·단위, 그룹 이름까지 읽는다.
    """
    out: set[str] = set()
    for user in data.ALL_USERS:
        headers = world.headers(user)
        out |= set(reachable_texts(client, world, user))
        for e in _get(client, "/schedule/events", headers, include_past=True).json():
            out |= {e["place"], e["memo"] or ""}
        for r in _get(client, "/schedule/requests", headers).json():
            out |= {r["place"], r["memo"]}
        out |= {h["unit"] for h in _get(client, "/schedule/check/items", headers).json()}
        out |= {
            i["kind_label"]
            for i in _get(client, "/ai-assistant/knowledge/items", headers, limit=LIMIT).json()
        }
        out.add(_get(client, "/family-group/groups/me", headers).json()["name"])
    out.discard("")
    return out


def snapshot(client: TestClient, world: World) -> dict:
    """이름·내용·날짜·상태만 담은 비교용 요약(id 는 다시 만들 때마다 달라서 뺀다)."""
    names = {m.user_id: m.name for m in world.members.values()}
    snap: dict = {"access": access_matrix(client, world)}
    snap["users"] = {}
    for name in data.ALL_USERS:
        headers = world.headers(name)
        group = _get(client, "/family-group/groups/me", headers).json()
        snap["users"][name] = {
            "group": group["name"],
            "group_role": group["my_role"],  # owner/admin/member: 그룹 안 권한
            "members": sorted((m["name"], m["group_role"]) for m in group["members"]),
            "rooms": sorted(
                (r["kind"], names.get(r["peer_user_id"], "") if r["peer_user_id"] else "")
                for r in _get(client, "/family-chat/rooms", headers).json()
            ),
        }
    snap["messages"] = {
        room: [
            (names.get(m["user_id"], "?"), m["text"], m["created_at"][:10])
            for m in _get(
                client, "/family-chat/messages", world.headers(data.ROOM_MEMBERS[room][0]),
                room_id=world.rooms[room], limit=LIMIT,
            ).json()
        ]
        for room in data.ROOM_MEMBERS
    }  # fmt: skip
    snap["events"] = {
        name: sorted(
            (
                (
                    e["title"], e["start_date"], e["start_time"], e["end_time"], e["status"],
                    e["source"], e["place"], e["memo"], e["kind"], names.get(e["user_id"], "?"),
                    tuple(sorted(names.get(i, "?") for i in e.get("shared_ids", []))),
                )
                for e in _get(client, "/schedule/events", world.headers(name), include_past=True).json()
            ),
            key=repr,
        )
        for name in data.ALL_USERS
    }  # fmt: skip
    snap["todos"] = {
        name: sorted(
            (
                (t["title"], names.get(t["assignee_id"]), t["due_date"], t["done"], t["source"])
                for t in _get(client, "/family-chat/todos", world.headers(name)).json()
            ),
            key=repr,
        )
        for name in data.ALL_USERS
    }
    snap["requests"] = {
        name: sorted(
            (
                (
                    r["title"], r["start_date"], names.get(r["from_id"], "?"), r["canceled"],
                    tuple(sorted((names.get(x["user_id"], "?"), x["status"]) for x in r["recipients"])),
                )
                for r in _get(client, "/schedule/requests", world.headers(name)).json()
            ),
            key=repr,
        )
        for name in data.ALL_USERS
    }  # fmt: skip
    snap["docs"] = {
        name: sorted(
            (
                (i["kind_label"], i["title"], i["occurred_on"], i["sensitivity"])
                for i in _get(client, "/ai-assistant/knowledge/items", world.headers(name), limit=LIMIT).json()
            ),
            key=repr,
        )
        for name in data.ALL_USERS
    }  # fmt: skip
    snap["expenses"] = {
        name: sorted(
            (e["date"], e["title"], e["amount"])
            for m in EXPENSE_MONTHS
            for e in _expenses(client, world.headers(name), m)
        )
        for name in data.ALL_USERS
    }
    snap["habits"] = {  # 기준 날짜를 명시해서 읽는다: 기록이 그날에 붙었는지도 비교된다
        name: sorted(
            (
                (h["name"], h["kind"], h["goal"], h["unit"], h["shared"], h["done"], h["count"])
                for h in _get(
                    client, "/schedule/check/items", world.headers(name), date=data.REFERENCE_DAY
                ).json()
            ),
            key=repr,
        )
        for name in data.ALL_USERS
    }
    return snap


def unexpected_detections(texts) -> list[tuple[str, str]]:
    """개인정보 탐지기가 찾은 구간 중 코드에 선언된 허구의 값(이름·표식 번호)이 아닌 것: (글, 찾은 값).

    이것은 보조 신호다. 규칙 기반 탐지기는 사전에 없는 이름이나 일부 번호 형식을 찾지 못하므로(NER 이 꺼져 있을 때 '김철수' 같은 이름은 탐지되지 않는다)
    '탐지 0건'은 합성이라는 증거가 아니다. 합성 보장은 저장된 모든 글이 코드 선언 안에 있는지 보는 시험(`stored_texts <= data.all_texts()`)이 맡는다.
    """
    from app.shared.privacy.detectors import detect

    allowed = data.FICTIONAL_NAMES | data.FICTIONAL_SENSITIVE
    problems = []
    for text in texts:
        for span in detect(text, known_names=tuple(data.FICTIONAL_NAMES)):
            found = text[span.start : span.end]
            if found not in allowed:
                problems.append((text, found))
    return problems
