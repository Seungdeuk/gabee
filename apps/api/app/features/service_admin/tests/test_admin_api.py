"""서비스 관리자 API(/admin)의 안쪽 문: Bearer 정식 회원 + SERVICE_ADMIN_USER_IDS 허용 목록만 통과한다.

허용 목록에는 시험에서 만든 가짜 계정의 id 만 넣는다(실제 운영 id 는 어디에도 쓰지 않는다)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.features.family_group.models import GroupMember, JoinRequest, User
from app.shared.ai_usage import AiGroupSetting, AiUsageLog
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

ME = "/admin/service/me"
PASSWORD = "Sunny-day-2026"


def _login(client, login_id="jimin_kim") -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post("/family-group/auth/login", json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


def _group_of(user_id: str) -> str:
    with SessionLocal() as db:
        return db.get(User, user_id).active_group_id


@pytest.fixture
def make_admin(monkeypatch):
    """서비스 관리자 허용 목록에 시험 계정 id 를 넣는다. 시험이 끝나면 원래 값(빈 목록)으로 돌아간다."""
    monkeypatch.setattr(settings, "service_admin_user_ids", "")
    monkeypatch.setattr(settings, "ops_admin_user_ids", "")

    def add(user_id: str) -> None:
        settings.service_admin_user_ids = ",".join(
            filter(None, [settings.service_admin_user_ids, user_id])
        )

    return add


def _denied(r) -> bool:
    return r.status_code == 403 and r.json()["code"] == "operator_required"


def test_requires_login(client):
    assert client.get(ME).status_code == 401


def test_new_member_is_not_admin(client, make_admin):
    headers, _ = _login(client)
    assert _denied(client.get(ME, headers=headers))


def test_listed_member_passes(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    r = client.get(ME, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": user_id, "name": "김지민", "login_id": "jimin_kim"}


def test_family_owner_role_is_not_admin(client, make_admin):
    headers, user_id = _login(client)
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    with SessionLocal() as db:
        assert db.get(GroupMember, (db.get(User, user_id).active_group_id, user_id)).role == "owner"
    assert _denied(client.get(ME, headers=headers))


def test_ops_admin_list_is_not_service_admin(client, make_admin):
    headers, user_id = _login(client)
    settings.ops_admin_user_ids = (
        user_id  # 운영(인프라) 관리자 목록은 서비스 관리자를 포함하지 않는다
    )
    assert _denied(client.get(ME, headers=headers))


LISTS = (
    "/admin/service/members",
    "/admin/service/groups",
    "/admin/service/features",
    "/admin/service/ai-usage",
    "/admin/service/support",
)


def test_lists_are_admin_only(client, make_admin):
    for path in LISTS:
        assert client.get(path).status_code == 401, path
    headers, _ = _login(client)
    for path in LISTS:
        assert _denied(client.get(path, headers=headers)), path


def test_lists_count_members_and_groups(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    r = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    assert r.status_code in (200, 201), r.text

    members = client.get("/admin/service/members", headers=headers).json()
    assert members["total"] >= 1 and members["joined_this_week"] >= 1
    me = next(r for r in members["rows"] if r["id"] == user_id)
    assert me["has_family"] is True and me["last_login_at"] is not None
    assert "email" not in me  # 이메일은 돌려주지 않는다
    assert me["email_verified"] is False

    groups = client.get("/admin/service/groups", headers=headers).json()
    assert groups["total"] == 1
    assert groups["rows"][0]["name"] == "우리 가족" and groups["rows"][0]["members"] == 1
    assert groups["sizes"] == [{"members": 1, "groups": 1}]

    features = client.get("/admin/service/features", headers=headers).json()
    assert [r["key"] for r in features["rows"]] == ["schedule", "chat", "billing"]
    assert features["families_total"] == 1


def test_members_summary(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    _login(client, "minsu_park")  # 가족 없음
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    with SessionLocal() as db:
        db.execute(
            update(User).where(User.id == user_id).values(email_verified_at=datetime.now(UTC))
        )
        db.commit()

    d = client.get("/admin/service/members", headers=headers).json()
    assert d["total"] == 2
    assert d["active_7d"] == 2  # 둘 다 방금 로그인했다
    assert d["no_family"] == 1
    assert d["email_verified"] == 1
    flags = {r["id"]: r["email_verified"] for r in d["rows"]}
    assert flags[user_id] is True and list(flags.values()).count(False) == 1
    assert all("email" not in r for r in d["rows"])


def test_groups_summary(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    h2, u2 = _login(client, "minsu_park")
    client.post("/family-group/groups", json={"name": "둘째 가족"}, headers=h2)
    g1, g2 = _group_of(user_id), _group_of(u2)
    old = datetime.now(UTC) - timedelta(days=2)
    with SessionLocal() as db:
        db.add_all(
            [
                JoinRequest(group_id=g1, user_id="u_a", invite_id="i_a", requested_at=old),
                JoinRequest(group_id=g1, user_id="u_b", invite_id="i_b"),
                JoinRequest(
                    group_id=g2,
                    user_id="u_c",
                    invite_id="i_c",
                    status="approved",
                    requested_at=old - timedelta(days=5),
                ),
                AiGroupSetting(group_id=g1, enabled=True),
                AiGroupSetting(group_id=g2, enabled=False),
            ]
        )
        db.commit()

    d = client.get("/admin/service/groups", headers=headers).json()
    assert d["total"] == 2 and d["single_member"] == 2
    assert d["pending_total"] == 2
    assert d["oldest_pending_at"][:16] == old.isoformat()[:16]  # 처리된 요청은 빼고 센다
    assert d["ai_enabled"] == 1
    rows = {r["id"]: r for r in d["rows"]}
    assert (rows[g1]["pending"], rows[g1]["ai_enabled"]) == (2, True)
    assert (rows[g2]["pending"], rows[g2]["ai_enabled"]) == (0, False)


def test_groups_summary_empty(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    d = client.get("/admin/service/groups", headers=headers).json()
    assert (d["single_member"], d["pending_total"], d["ai_enabled"]) == (0, 0, 0)
    assert d["oldest_pending_at"] is None


def test_ai_usage_excludes_markers_and_lists(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    h2, u2 = _login(client, "minsu_park")
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    now = datetime.now(UTC)
    g = "g1"

    def row(uid, status, feature="analysis", code=None, at=now, group=g):
        return AiUsageLog(
            group_id=group,
            user_id=uid,
            status=status,
            feature=feature,
            error_code=code,
            created_at=at,
        )

    with SessionLocal() as db:
        db.add_all(
            [
                row(user_id, "ok"),
                row(user_id, "error"),
                row(user_id, "nested", "reply"),
                row(u2, "ok", "reply"),
                row(u2, "rejected", code="ai_cooldown"),
                row(u2, "rejected", code="ai_daily_limit_user", at=now - timedelta(hours=1)),
                row(u2, "rejected", code="ai_daily_limit_user", at=now - timedelta(days=2)),
                row(
                    u2, "rejected", code="ai_daily_limit_group", at=now - timedelta(days=2, hours=1)
                ),
                row(user_id, "rejected", code="ai_cooldown", at=now - timedelta(days=1)),
            ]
        )
        db.commit()

    d = client.get("/admin/service/ai-usage", headers=headers).json()
    assert (d["today"], d["week"], d["month"]) == (3, 3, 3)
    assert sum(d["daily"]) == 3
    # 기능별로는 비서가 안에서 부른 에이전트(nested)도 따로 나눠 센다. 한도 거절은 뺀다
    assert {r["key"]: (r["calls"], r["direct"], r["via_assistant"]) for r in d["rows"]} == {
        "analysis": (2, 2, 0),
        "reply": (2, 1, 1),
    }

    assert d["families"] == [{"group_id": g, "name": None, "requests": 3, "errors": 1}]
    by_user = {r["user_id"]: r for r in d["users"]}
    assert by_user[user_id]["requests"] == 2 and by_user[user_id]["errors"] == 1
    assert by_user[user_id]["name"] == "김지민" and by_user[user_id]["login_id"] == "jimin_kim"
    assert by_user[u2]["requests"] == 1 and by_user[u2]["errors"] == 0
    assert d["users"][0]["user_id"] == user_id  # 요청 많은 순

    assert len(d["limited"]) == 1  # ai_cooldown 거절은 한도 기록이 아니다
    lim = d["limited"][0]
    assert lim["user_id"] == u2 and lim["name"] == "김지민"
    assert lim["days"] == 2
    assert lim["group_name"] is None
    assert lim["last_at"][:16] == (now - timedelta(hours=1)).isoformat()[:16]


def test_ai_usage_counts_requests(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    now = datetime.now(UTC)
    log = {"group_id": "g1", "user_id": user_id, "status": "ok"}
    with SessionLocal() as db:
        db.add_all(
            [
                AiUsageLog(**log, feature="assistant_chat", api_calls=4, created_at=now),
                # 캐시 적중도 사용자가 요청한 1번으로 센다
                AiUsageLog(**log, feature="assistant_chat", api_calls=0, created_at=now),
                AiUsageLog(
                    **log, feature="analysis", api_calls=1, created_at=now - timedelta(days=3)
                ),
                AiUsageLog(
                    **log, feature="analysis", api_calls=1, created_at=now - timedelta(days=40)
                ),
            ]
        )
        db.commit()

    r = client.get("/admin/service/ai-usage", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["today"], d["week"], d["month"]) == (2, 3, 3)
    assert len(d["daily"]) == 14 and d["daily"][-1] == 2 and sum(d["daily"]) == 3
    assert d["rows"] == [
        {
            "key": "assistant_chat",
            "name": "AI 비서 채팅",
            "calls": 2,
            "direct": 2,
            "via_assistant": 0,
        },
        {"key": "analysis", "name": "가족 채팅 분석", "calls": 1, "direct": 1, "via_assistant": 0},
    ]


def test_legacy_token_cannot_reach_admin_even_if_listed(client, make_admin):
    headers = signup(client, "익명")
    user_id = client.get("/family-group/me", headers=headers).json()["id"]
    make_admin(user_id)
    assert client.get(ME, headers=headers).status_code == 401


def test_support_list_and_answer(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    h2, _ = _login(client, "minsu_park")
    send = lambda h, kind, title: client.post(  # noqa: E731
        "/support/tickets", json={"kind": kind, "title": title, "body": "내용"}, headers=h
    ).json()["id"]
    first = send(headers, "inquiry", "비밀번호 바꾸기")
    second = send(h2, "report", "광고 메시지")

    d = client.get("/admin/service/support", headers=headers).json()
    assert (d["new"], d["working"], d["done"], d["reports"]) == (2, 0, 0, 1)
    assert [r["id"] for r in d["rows"]] == [second, first]  # 최근순
    row = d["rows"][1]
    assert (row["user_name"], row["login_id"], row["group_name"]) == (
        "김지민",
        "jimin_kim",
        "우리 가족",
    )
    assert d["rows"][0]["group_name"] is None  # 가족 없는 회원

    r = client.patch(
        f"/admin/service/support/{second}", json={"status": "working"}, headers=headers
    )
    assert r.status_code == 204, r.text
    r = client.patch(
        f"/admin/service/support/{first}",
        json={"status": "done", "answer": " 설정에서 바꿀 수 있어요 "},
        headers=headers,
    )
    assert r.status_code == 204, r.text

    d = client.get("/admin/service/support", headers=headers).json()
    assert (d["new"], d["working"], d["done"]) == (0, 1, 1)
    mine = client.get("/support/tickets/mine", headers=headers).json()["rows"][0]
    assert (mine["status"], mine["answer"]) == ("done", "설정에서 바꿀 수 있어요")
    assert mine["answered_at"] is not None


def test_support_update_rules(client, make_admin):
    headers, user_id = _login(client)
    h2, _ = _login(client, "minsu_park")
    tid = client.post(
        "/support/tickets", json={"kind": "inquiry", "title": "질문", "body": "내용"}, headers=h2
    ).json()["id"]
    path = f"/admin/service/support/{tid}"
    assert client.patch(path, json={"status": "done"}).status_code == 401
    assert _denied(client.patch(path, json={"status": "done"}, headers=headers))  # 허용 목록에 없음
    make_admin(user_id)
    assert client.patch(path, json={}, headers=headers).status_code == 422  # 바꿀 것이 없음
    assert client.patch(path, json={"status": "closed"}, headers=headers).status_code == 422
    assert (
        client.patch(
            "/admin/service/support/nope", json={"status": "done"}, headers=headers
        ).status_code
        == 404
    )
    # 문의를 보낸 사용자 본인도 허용 목록에 없으면 상태를 바꿀 수 없다
    assert _denied(client.patch(path, json={"status": "done"}, headers=h2))


def test_support_answer_notifies_sender_without_family(client, make_admin):
    admin, admin_id = _login(client)
    make_admin(admin_id)
    sender, _ = _login(client, "minsu_park")  # 가족 없는 회원
    tid = client.post(
        "/support/tickets",
        json={"kind": "inquiry", "title": "비밀 제목", "body": "비밀 내용"},
        headers=sender,
    ).json()["id"]
    path = f"/admin/service/support/{tid}"
    inbox = lambda h: client.get("/notifications", headers=h).json()["items"]  # noqa: E731

    assert client.patch(path, json={"status": "working"}, headers=admin).status_code == 204
    assert inbox(sender) == []  # 상태만 바꾸면 알림이 없다

    r = client.patch(path, json={"status": "done", "answer": "비밀 답변"}, headers=admin)
    assert r.status_code == 204, r.text
    items = inbox(sender)
    assert [(n["kind"], n["event"], n["title"], n["target_id"]) for n in items] == [
        ("support", "ticket_answered", "문의에 답변이 달렸어요", tid)
    ]
    assert not any(word in str(items) for word in ("비밀 제목", "비밀 내용", "비밀 답변"))
    assert inbox(admin) == []  # 답변한 관리자에게는 가지 않는다

    client.patch(path, json={"answer": "비밀 답변"}, headers=admin)  # 같은 답변 다시 저장
    assert len(inbox(sender)) == 1
    client.patch(path, json={"answer": "고친 답변"}, headers=admin)  # 답변을 고치면 다시 알린다
    assert len(inbox(sender)) == 2
