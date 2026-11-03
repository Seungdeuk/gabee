"""보안 시험 묶음(test_security_matrix.py)이 쓰는 보조 코드.

- FakeHttp: `httpx.post` 하나를 가짜로 바꿔 서버가 밖으로 내보내는 모든 요청(Anthropic·로컬 LLM·기타)을 기록한다.
  서버의 LLM 호출은 전부 `httpx.post` 를 거치므로(app/shared/llm/client.py, agent.py, knowledge/rag_chat.py 등) 이 한 곳만 막으면
  어떤 경로도 실제 Claude 에 닿지 못한다. 실제 Anthropic·외부 API 는 절대 부르지 않는다.
- World: 가족 A·B(각 소유자·일반 구성원)와 가족 없는 사용자, 가족 B 의 리소스 id 모음.
모든 이름·번호·주소는 시험용 합성 값이다.
"""

import io
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image

ANTHROPIC_HOST = "api.anthropic.com"

PHONE = "010-4321-8765"
EMAIL = "secret.person@example.com"
ADDR = "서울특별시 송파구 올림픽로 300"
RRN = "900101-1234568"  # 검증 숫자가 맞는 합성 주민등록번호
CARD = "4539 1488 0343 6467"  # Luhn 이 맞는 시험용 카드 번호
ACCOUNT = "국민은행 123456-04-123456"


def jpeg_bytes(size=(40, 30), color=(30, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def example_from_schema(schema: dict) -> Any:
    """구조화 출력 스키마에 맞는 가장 단순한 값(검증을 통과할 만큼만 채운다)."""
    kind = schema.get("type")
    if "enum" in schema:
        return "not_schedule" if "not_schedule" in schema["enum"] else schema["enum"][0]
    if kind == "object":
        return {k: example_from_schema(v) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        item = schema.get("items", {})
        # 문자열 목록(답장·주제 후보 등)은 비어 있으면 서버가 오류로 보므로 한 개 채운다
        return ["확인했어요"] if item.get("type") == "string" else []
    if kind == "string":
        return "요약"
    if kind == "integer":
        return 0
    if kind == "boolean":
        return False
    return None


@dataclass
class Recorded:
    url: str
    body: dict

    @property
    def text(self) -> str:
        """요청 본문 전체(프롬프트·시스템·도구 결과 포함)를 한 문자열로."""
        return json.dumps(self.body, ensure_ascii=False)

    @property
    def is_anthropic(self) -> bool:
        return ANTHROPIC_HOST in self.url


@dataclass
class FakeHttp:
    """httpx.post 대용. calls 에 (url, body) 를 쌓는다. tool_plan 이 있으면 에이전트 호출에서 그 도구를 먼저 부른 뒤 글자로 답한다."""

    calls: list[Recorded] = field(default_factory=list)
    tool_plan: list[tuple[str, dict]] = field(default_factory=list)
    _plan_pos: int = 0

    def reset(self) -> None:
        self.calls.clear()
        self.tool_plan = []
        self._plan_pos = 0

    @property
    def anthropic(self) -> list[Recorded]:
        return [c for c in self.calls if c.is_anthropic]

    @property
    def other(self) -> list[Recorded]:
        return [c for c in self.calls if not c.is_anthropic]

    def __call__(self, url, *args, **kwargs) -> httpx.Response:
        body = kwargs.get("json") or {}
        rec = Recorded(str(url), body)
        self.calls.append(rec)
        request = httpx.Request("POST", str(url))
        if not rec.is_anthropic:  # 로컬 LLM·Jev 등: 응답 실패로 돌려 서버가 대체 동작을 쓰게 한다
            return httpx.Response(503, json={"error": "blocked-by-test"}, request=request)
        usage = {"input_tokens": 11, "output_tokens": 7}
        if "tools" in body:  # 에이전트·도구 루프
            if self._plan_pos < len(self.tool_plan):
                name, args = self.tool_plan[self._plan_pos]
                self._plan_pos += 1
                content = [
                    {"type": "tool_use", "id": f"tu{self._plan_pos}", "name": name, "input": args}
                ]
                return httpx.Response(
                    200,
                    json={"content": content, "usage": usage, "stop_reason": "tool_use"},
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "알겠어요. 확인했어요."}],
                    "usage": usage,
                    "stop_reason": "end_turn",
                },
                request=request,
            )
        schema = ((body.get("output_config") or {}).get("format") or {}).get("schema")
        text = (
            json.dumps(example_from_schema(schema), ensure_ascii=False)
            if schema
            else "알겠어요. 확인했어요."
        )
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": text}],
                "usage": usage,
                "stop_reason": "end_turn",
                "model": body.get("model", "claude-test"),
            },
            request=request,
        )


# ---------------------------------------------------------------- World
@dataclass
class Person:
    name: str
    headers: dict
    id: str


@dataclass
class Family:
    owner: Person  # 부모 역할 + 가족 소유자
    member: Person  # 자녀 역할 + 일반 구성원
    third: Person  # 자녀 역할 + 일반 구성원(1:1 방 비참여자 역할)
    group_id: str = ""
    invite_code: str = ""
    tag: str = ""  # 이 가족의 데이터에만 들어 있는 영문 표식(다른 가족의 응답에 나오면 유출)
    seeds: dict = field(default_factory=dict)  # 리소스 이름 -> id


def _person(client, name: str, role: str) -> Person:
    r = client.post("/family-group/users", json={"name": name, "role": role})
    assert r.status_code == 201, r.text
    headers = {"X-Gyeot-Token": r.json()["token"]}
    me = client.get("/family-group/me", headers=headers)
    assert me.status_code == 200, me.text
    return Person(name, headers, me.json()["id"])


def new_family(client, label: str, tag: str = "") -> Family:
    """가족 하나(소유자·일반 구성원·또 다른 구성원). label 로 이름이 겹치지 않게 하고 tag 는 데이터 표식이다."""
    from tests.helpers import join_family

    owner = _person(client, f"{label}소유", "parent")
    group = client.post(
        "/family-group/groups", json={"name": f"{label} 가족"}, headers=owner.headers
    )
    assert group.status_code == 201, group.text
    g = group.json()
    member = _person(client, f"{label}멤버", "child")
    third = _person(client, f"{label}셋째", "child")
    join_family(client, owner.headers, g["invite_code"], member.headers)
    join_family(client, owner.headers, g["invite_code"], third.headers)
    return Family(owner, member, third, g["id"], g["invite_code"], tag or label)


def seed_resources(client, fam: Family) -> None:
    """가족의 모든 종류 리소스를 API 로 하나씩 만들고 id 를 fam.seeds 에 담는다(소유자가 만든 것)."""
    s, h = fam.seeds, fam.owner.headers
    secret = f"ZZ{fam.tag}"

    def ok(r, code=(200, 201)):
        assert r.status_code in code, (r.request.url, r.status_code, r.text)
        return r

    s["secret"] = secret
    m = ok(
        client.post("/family-chat/messages", json={"text": f"{secret} 가족방 메시지"}, headers=h)
    ).json()
    s["message_id"] = m["id"]
    room = ok(
        client.post("/family-chat/rooms/direct", json={"user_id": fam.member.id}, headers=h)
    ).json()
    s["direct_room_id"] = room["id"]
    dm = ok(
        client.post(
            "/family-chat/messages",
            json={"text": f"{secret} 1대1 메시지", "room_id": room["id"]},
            headers=h,
        )
    ).json()
    s["direct_message_id"] = dm["id"]
    ph = ok(
        client.post(
            "/family-chat/photos",
            files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")},
            headers=h,
        )
    ).json()
    s["photo_message_id"] = ph["id"]
    s["attachment_id"] = ph["attachment"]["id"]
    ok(client.post("/family-chat/pins", json={"message_id": m["id"]}, headers=h))
    s["todo_id"] = ok(
        client.post("/family-chat/todos", json={"title": f"{secret} 할일"}, headers=h)
    ).json()["id"]
    from datetime import UTC, datetime, timedelta

    soon = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    s["event_id"] = ok(
        client.post(
            "/schedule/events", json={"title": f"{secret} 일정", "starts_at": soon}, headers=h
        )
    ).json()["id"]
    exp = ok(
        client.post(
            "/billing/expenses",
            json={
                "title": f"{secret} 지출",
                "amount": 30000,
                "date": datetime.now(UTC).date().isoformat(),
            },
            headers=h,
        )
    ).json()
    s["expense_id"] = exp["id"]
    s["subscription_id"] = ok(
        client.post(
            "/billing/subscriptions",
            json={"kind": "ott", "name": f"{secret} 구독", "monthly_fee": 10000},
            headers=h,
        )
    ).json()["id"]
    s["child_id"] = fam.member.id
    ok(
        client.post(
            f"/billing/allowances/{fam.member.id}/credits",
            json={"amount": 5000, "memo": secret},
            headers=h,
        )
    )
    req = ok(
        client.post(
            f"/billing/allowances/{fam.member.id}/requests",
            json={"amount": 1000, "memo": secret},
            headers=fam.member.headers,
        )
    ).json()
    kid = next(x for x in req if x["child_id"] == fam.member.id) if isinstance(req, list) else req
    s["allowance_request_id"] = kid["requests"][0]["id"]
    s["allowance_entry_id"] = kid["entries"][0]["id"]
    ki = ok(
        client.post(
            "/ai-assistant/knowledge/items",
            json={
                "kind_label": "메모",
                "title": f"{secret} 문서",
                "body_md": f"{secret} 본문 보안시험",
            },
            headers=h,
        )
    ).json()
    s["knowledge_item_id"] = ki["id"]
    s["ai_photo_id"] = ok(
        client.post(
            "/ai-assistant/photos", files={"file": ("p.jpg", jpeg_bytes(), "image/jpeg")}, headers=h
        )
    ).json()["id"]
    s["file_id"] = ok(
        client.post(
            "/ai-assistant/files",
            files={"file": ("memo.txt", f"{secret} 파일 본문".encode(), "text/plain")},
            headers=h,
        )
    ).json()["id"]
    code = ok(client.post("/family-group/groups/invites/reissue", headers=h)).json()["invite_code"]
    waiting = _person(client, f"{fam.owner.name[:-2]}대기", "child")
    r = ok(client.post("/family-group/groups/join", json={"code": code}, headers=waiting.headers))
    s["join_request_id"] = r.json()["id"]
    s["waiting_user_id"] = waiting.id
    s["_waiting"] = waiting
    s["owner_id"] = fam.owner.id
    s["third_id"] = fam.third.id
    s["pinned_message_id"] = m["id"]
    s.update(fresh(client, fam, "pdf_file_id"))
    s.update(fresh(client, fam, "payment_id"))


# ---------------------------------------------------------------- 대조 시험용: 소비되는 리소스를 새로 만든다
def this_month() -> str:
    """현재 달(YYYY-MM). 시드 지출 날짜(UTC 오늘)와 같은 기준이라 달이 바뀌어도 시험이 깨지지 않는다."""
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()[:7]


def month_ago(n: int) -> str:
    """n 개월 전(YYYY-MM). 송금 완료 표시가 있는 달은 잠기므로 시험마다 다른 달을 쓴다."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    index = today.year * 12 + (today.month - 1) - n
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def pdf_bytes(text: str = "Security test memo document") -> bytes:
    """글자 층이 있는 한 쪽짜리 유효한 PDF(손으로 만든 것, 새 의존성 없음). OCR 없이 서버가 읽어 문서로 저장한다."""
    nl = b"\n"
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>" % len(stream) + nl + b"stream" + nl + stream + nl + b"endstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4" + nl, []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj" % i + nl + body + nl + b"endobj" + nl
    xref = len(out)
    out += b"xref" + nl + b"0 %d" % (len(objs) + 1) + nl + b"0000000000 65535 f " + nl
    for off in offsets:
        out += b"%010d 00000 n " % off + nl
    out += b"trailer<</Size %d/Root 1 0 R>>" % (len(objs) + 1) + nl
    out += b"startxref" + nl + b"%d" % xref + nl + b"%%EOF"
    return out


FRESH_KEYS = (
    "message_id",
    "direct_message_id",
    "attachment_id",
    "todo_id",
    "event_id",
    "expense_id",
    "subscription_id",
    "knowledge_item_id",
    "file_id",
    "pdf_file_id",
    "allowance_request_id",
    "allowance_entry_id",
    "join_request_id",
    "payment_id",
)


def fresh(client, fam: Family, key: str) -> dict:
    """key 에 해당하는 리소스를 새로 만들어 {키: id, ...} 로 돌려준다(요청 하나가 소비해도 다른 항목에 영향이 없게)."""
    from datetime import UTC, datetime, timedelta

    h, secret = fam.owner.headers, f"ZZ{fam.tag}"

    def ok(r, code=(200, 201)):
        assert r.status_code in code, (r.request.url, r.status_code, r.text)
        return r.json() if r.content else {}

    def expense(date: str) -> str:
        return ok(
            client.post(
                "/billing/expenses",
                json={"title": f"{secret} 지출", "amount": 30000, "date": date},
                headers=h,
            )
        )["id"]

    if key == "message_id":
        return {
            key: ok(
                client.post(
                    "/family-chat/messages", json={"text": f"{secret} 새 메시지"}, headers=h
                )
            )["id"]
        }
    if key == "direct_message_id":
        room = ok(
            client.post("/family-chat/rooms/direct", json={"user_id": fam.member.id}, headers=h)
        )["id"]
        msg = ok(
            client.post(
                "/family-chat/messages",
                json={"text": f"{secret} 새 1대1", "room_id": room},
                headers=h,
            )
        )
        return {key: msg["id"]}
    if key == "attachment_id":
        ph = ok(
            client.post(
                "/family-chat/photos",
                files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")},
                headers=h,
            )
        )
        return {key: ph["attachment"]["id"]}
    if key == "todo_id":
        return {
            key: ok(
                client.post("/family-chat/todos", json={"title": f"{secret} 새 할일"}, headers=h)
            )["id"]
        }
    if key == "event_id":
        soon = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        return {
            key: ok(
                client.post(
                    "/schedule/events",
                    json={"title": f"{secret} 새 일정", "starts_at": soon},
                    headers=h,
                )
            )["id"]
        }
    if key == "expense_id":
        return {key: expense(datetime.now(UTC).date().isoformat())}
    if key == "subscription_id":
        body = {"kind": "ott", "name": f"{secret} 새 구독", "monthly_fee": 10000}
        return {key: ok(client.post("/billing/subscriptions", json=body, headers=h))["id"]}
    if key == "knowledge_item_id":
        body = {
            "kind_label": "메모",
            "title": f"{secret} 새 문서",
            "body_md": f"{secret} 새 본문 보안시험",
        }
        return {key: ok(client.post("/ai-assistant/knowledge/items", json=body, headers=h))["id"]}
    if key == "file_id":
        files = {"file": ("memo.txt", f"{secret} 새 파일".encode(), "text/plain")}
        return {key: ok(client.post("/ai-assistant/files", files=files, headers=h))["id"]}
    if key == "pdf_file_id":
        files = {
            "file": (
                "doc.pdf",
                pdf_bytes(f"Security test memo document {secret} pdf contents here"),
                "application/pdf",
            )
        }
        return {key: ok(client.post("/ai-assistant/files", files=files, headers=h))["id"]}
    if key == "allowance_request_id":
        out = ok(
            client.post(
                f"/billing/allowances/{fam.member.id}/requests",
                json={"amount": 500, "memo": secret},
                headers=fam.member.headers,
            )
        )
        pending = [r for r in out["requests"] if r["status"] == "pending"]
        return {key: pending[-1]["id"]}
    if key == "allowance_entry_id":
        out = ok(
            client.post(
                f"/billing/allowances/{fam.member.id}/credits",
                json={"amount": 300, "memo": "fresh-entry"},
                headers=h,
            )
        )
        return {key: next(e for e in out["entries"] if e["memo"] == "fresh-entry")["id"]}
    if key == "join_request_id":
        code = ok(client.post("/family-group/groups/invites/reissue", headers=h))["invite_code"]
        waiting = _person(client, f"{fam.owner.name[:-2]}대기{fam.seeds.get('_n', 0)}", "child")
        fam.seeds["_n"] = fam.seeds.get("_n", 0) + 1
        req = ok(
            client.post("/family-group/groups/join", json={"code": code}, headers=waiting.headers)
        )
        return {key: req["id"], "_waiting": waiting}
    if key in ("payment_id", "settlement_ready"):
        if key == "payment_id":
            fam.seeds["_pm"] = fam.seeds.get("_pm", 0) + 1
            month = month_ago(fam.seeds["_pm"])
        else:
            month = this_month()
        exp = expense(f"{month}-15")
        ok(
            client.post(
                "/billing/settlement/tag",
                json={"month": month, "expense_ids": [exp], "tag": "all"},
                headers=h,
            )
        )
        if key == "settlement_ready":
            return {}
        board = ok(client.get("/billing/settlement", params={"month": month}, headers=h))
        tr = board["transfers"][0]
        done = ok(
            client.post(
                "/billing/settlement/payments",
                json={
                    "month": month,
                    "from_user_id": tr["from_user_id"],
                    "to_user_id": tr["to_user_id"],
                    "amount": tr["amount"],
                },
                headers=h,
            )
        )
        return {key: done["completed"][-1]["id"]}
    raise KeyError(key)
