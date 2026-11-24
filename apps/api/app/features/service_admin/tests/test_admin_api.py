"""서비스 관리자 API(/admin)의 안쪽 문: Bearer 정식 회원 + ADMIN_USER_IDS(통합관리자) 허용 목록만 통과한다.

허용 목록에는 시험에서 만든 가짜 계정의 id 만 넣는다(실제 운영 id 는 어디에도 쓰지 않는다)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.features.family_group.models import GroupMember, JoinRequest, User
from app.shared.ai_guard import day_start
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
    """통합관리자 허용 목록에 시험 계정 id 를 넣는다. 시험이 끝나면 원래 값(빈 목록)으로 돌아간다."""
    monkeypatch.setattr(settings, "admin_user_ids", "")

    def add(user_id: str) -> None:
        settings.admin_user_ids = ",".join(filter(None, [settings.admin_user_ids, user_id]))

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


def test_one_admin_list_opens_service_and_ops(client, make_admin):
    """권한은 통합관리자 하나(2026-11-06): 같은 목록으로 서비스 관리와 운영 관리가 함께 열린다."""
    headers, user_id = _login(client)
    assert _denied(client.get(ME, headers=headers))
    assert _denied(client.get("/admin/ops/summary", headers=headers))
    make_admin(user_id)
    assert client.get(ME, headers=headers).status_code == 200
    assert client.get("/admin/ops/summary", headers=headers).status_code == 200


LISTS = (
    "/admin/service/members",
    "/admin/service/groups",
    "/admin/service/features",
    "/admin/service/ai-usage",
    "/admin/service/support",
    "/admin/service/notices",
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
    daily = members["daily_joined"]  # 30일 전 → 오늘, 방금 가입한 사람은 오늘 칸에 든다
    assert len(daily) == 30 and daily[-1] >= 1 and sum(daily) <= members["total"]
    # 카드별 날짜 그래프: 오늘 칸은 카드 숫자와 같다(누적 항목), 방금 로그인했으니 오늘 활성 1명 이상
    for field in ("daily_total", "daily_active", "daily_no_family", "daily_verified"):
        assert len(members[field]) == 30, field
    assert members["daily_total"][-1] == members["total"]
    assert members["daily_no_family"][-1] == members["no_family"]
    assert members["daily_verified"][-1] == members["email_verified"]
    assert members["daily_active"][-1] >= 1
    assert members["daily_total"] == sorted(members["daily_total"])  # 누적은 줄지 않는다
    me = next(r for r in members["rows"] if r["id"] == user_id)
    assert me["has_family"] is True and me["last_login_at"] is not None
    assert "email" not in me  # 이메일은 돌려주지 않는다
    assert me["email_verified"] is False

    groups = client.get("/admin/service/groups", headers=headers).json()
    assert groups["total"] == 1
    # 가족 이름은 첫 글자만 보이고 나머지는 가린다("우리 가족" → "우****")
    assert groups["rows"][0]["name"] == "우****" and groups["rows"][0]["members"] == 1
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


def _two_days_ago_noon(now: datetime) -> datetime:
    """2일 전 한국 날짜의 정오. `now - 2일 - 1시간` 처럼 잡으면 한국 시간 00~01시(또 월·연 경계)에 실행할 때 두 기록이 서로 다른
    날짜가 돼 '한도에 막힌 날 수'가 시각에 따라 달라진다(집계 규칙 오류가 아니라 시험 입력 문제). 정오 기준이면 항상 같은 날짜다."""
    return day_start(now) - timedelta(days=2) + timedelta(hours=12)


@pytest.mark.parametrize(
    "now_utc",
    [
        datetime(
            2026, 11, 18, 15, 30, tzinfo=UTC
        ),  # 한국 11/19 00:30 — 이 시각에 옛 입력은 3일로 셌다
        datetime(2026, 11, 18, 15, 59, tzinfo=UTC),  # 한국 00:59
        datetime(2026, 11, 19, 0, 16, tzinfo=UTC),  # 한국 09:16
        datetime(2026, 11, 19, 14, 59, tzinfo=UTC),  # 한국 23:59
        datetime(2026, 11, 30, 15, 10, tzinfo=UTC),  # 한국 12/01 00:10(월 경계)
        datetime(2026, 12, 31, 15, 30, tzinfo=UTC),  # 한국 2027/01/01 00:30(연 경계)
    ],
)
def test_limited_days_do_not_depend_on_the_hour_the_test_runs(now_utc):
    """같은 날 두 번, 다른 날 한 번 막힌 사람은 어느 시각에 시험해도 2일로 센다. 실제로 이틀에 걸친 기록은 그대로 3일이다."""
    from app.features.service_admin import service

    def days(times):
        hits = [{"user_id": "u", "name": "n", "group_name": None, "created_at": t} for t in times]
        return service._limited(hits)[0].days

    noon = _two_days_ago_noon(now_utc)
    assert days([now_utc - timedelta(hours=1), noon, noon - timedelta(hours=1)]) == 2
    # 집계 규칙 자체는 그대로: 서로 다른 한국 날짜 3개면 3일
    assert days([now_utc - timedelta(hours=1), noon, noon - timedelta(days=1)]) == 3


def test_ai_usage_excludes_markers_and_lists(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    h2, u2 = _login(client, "minsu_park")
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    now = datetime.now(UTC)
    g = "g1"

    two_days_ago_noon = _two_days_ago_noon(now)

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
                row(u2, "rejected", code="ai_daily_limit_user", at=two_days_ago_noon),
                row(
                    u2,
                    "rejected",
                    code="ai_daily_limit_group",
                    at=two_days_ago_noon - timedelta(hours=1),
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
    # 이름·아이디는 첫 글자만 보인다(김지민 → 김**, jimin_kim → j********)
    assert by_user[user_id]["name"] == "김**" and by_user[user_id]["login_id"] == "j********"
    assert by_user[u2]["requests"] == 1 and by_user[u2]["errors"] == 0
    assert d["users"][0]["user_id"] == user_id  # 요청 많은 순

    assert len(d["limited"]) == 1  # ai_cooldown 거절은 한도 기록이 아니다
    lim = d["limited"][0]
    assert lim["user_id"] == u2 and lim["name"] == "김**"
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
        "김**",
        "j********",
        "우****",
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
    r = client.patch(
        path, json={"answer": "고친 답변"}, headers=admin
    )  # 답변 수정은 되고 다시 알린다
    assert r.status_code == 204, r.text
    assert len(inbox(sender)) == 2
    mine = client.get("/support/tickets/mine", headers=sender).json()["rows"][0]
    assert (mine["status"], mine["answer"]) == ("done", "고친 답변")


def test_support_done_needs_answer(client, make_admin):
    """답변해야 답변 완료(done)가 된다. 답변을 저장하면 상태를 안 보내도 done 이 된다."""
    admin, admin_id = _login(client)
    make_admin(admin_id)
    sender, _ = _login(client, "minsu_park")
    tid = client.post(
        "/support/tickets",
        json={"kind": "inquiry", "title": "질문", "body": "내용"},
        headers=sender,
    ).json()["id"]
    path = f"/admin/service/support/{tid}"
    status = lambda: client.get("/support/tickets/mine", headers=sender).json()["rows"][0]["status"]  # noqa: E731

    r = client.patch(path, json={"status": "done"}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "answer_required")
    assert status() == "new"
    assert client.patch(path, json={"answer": "답변"}, headers=admin).status_code == 204
    assert status() == "done"  # 답변만 보내도 답변 완료
    # 답변이 있으면 다시 처리 중으로 돌렸다가 done 으로 바꾸는 것은 된다
    assert client.patch(path, json={"status": "working"}, headers=admin).status_code == 204
    assert client.patch(path, json={"status": "done"}, headers=admin).status_code == 204


def test_notice_write_edit_delete(client, make_admin):
    headers, user_id = _login(client)
    make_admin(user_id)
    user, _ = _login(client, "minsu_park")  # 가족 없는 일반 회원
    write = lambda title, category="info": client.post(  # noqa: E731
        "/admin/service/notices",
        json={"category": category, "title": f" {title} ", "body": " 내용\n둘째 줄 "},
        headers=headers,
    )
    r = write("점검 안내", "maintenance")
    assert r.status_code == 201, r.text
    first = r.json()
    assert (first["title"], first["body"], first["category"]) == (
        "점검 안내",
        "내용\n둘째 줄",
        "maintenance",
    )
    second = write("1.2 업데이트", "update").json()

    rows = client.get("/admin/service/notices", headers=headers).json()["rows"]
    assert [x["id"] for x in rows] == [second["id"], first["id"]]  # 최근순
    seen = client.get("/notices", headers=user).json()["rows"]
    assert [x["title"] for x in seen] == ["1.2 업데이트", "점검 안내"]
    assert "created_by" not in seen[0]

    path = f"/admin/service/notices/{first['id']}"
    r = client.put(
        path, json={"category": "info", "title": "점검 끝", "body": "끝났어요"}, headers=headers
    )
    assert r.status_code == 204, r.text
    edited = [
        x for x in client.get("/notices", headers=user).json()["rows"] if x["id"] == first["id"]
    ][0]
    assert (edited["category"], edited["title"], edited["body"]) == ("info", "점검 끝", "끝났어요")
    assert edited["updated_at"] >= edited["created_at"]

    assert client.delete(path, headers=headers).status_code == 204
    assert [x["id"] for x in client.get("/notices", headers=user).json()["rows"]] == [second["id"]]


def test_notice_rules(client, make_admin):
    headers, user_id = _login(client)
    body = {"category": "info", "title": "안내", "body": "내용"}
    assert client.post("/admin/service/notices", json=body).status_code == 401
    assert _denied(
        client.post("/admin/service/notices", json=body, headers=headers)
    )  # 허용 목록 밖
    assert _denied(client.delete("/admin/service/notices/nope", headers=headers))
    make_admin(user_id)
    bad = [
        {**body, "category": "event"},
        {**body, "title": ""},
        {**body, "body": ""},
        {**body, "title": "가" * 101},
    ]
    for b in bad:
        assert client.post("/admin/service/notices", json=b, headers=headers).status_code == 422
    assert client.put("/admin/service/notices/nope", json=body, headers=headers).status_code == 404
    assert client.delete("/admin/service/notices/nope", headers=headers).status_code == 404


def test_analytics_shape_and_counts(client, make_admin):
    """데이터 분석: 가입·가족·문의 답변이 퍼널·가족·고객 응대 숫자에 들어가고, 아직 지나지 않은 주는 None 이다."""
    headers, user_id = _login(client)
    make_admin(user_id)
    _login(client, "minsu_park")  # 가족 없는 회원
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    tid = client.post(
        "/support/tickets",
        json={"kind": "report", "title": "광고", "body": "내용"},
        headers=headers,
    ).json()["id"]
    client.patch(f"/admin/service/support/{tid}", json={"answer": "확인했어요"}, headers=headers)

    r = client.get("/admin/service/analytics", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["users"] >= 2 and len(d["retention"]) == 8 and len(d["heatmap"]) == 7
    assert all(len(row) == 24 for row in d["heatmap"]) and sum(map(sum, d["heatmap"])) >= 2
    this_week = d["retention"][-1]
    assert this_week["size"] >= 2 and this_week["w1"] is None  # 이번 주 가입자는 1주가 안 지났다
    steps = {s["key"]: s for s in d["funnel"]}
    assert steps["signup"]["users"] == d["users"] and steps["signup"]["share"] == 100.0
    assert 1 <= steps["family"]["users"] < d["users"]  # 가족을 만든 사람만
    assert d["families"]["solo_families"] >= 1 and d["total_families"] >= 1
    assert [f["key"] for f in d["features"]] == ["schedule", "chat", "billing", "ai"]
    s = d["support"]
    assert (s["reports"], s["answered"]) == (1, 1) and s["avg_hours"] is not None
    assert len(s["weekly"]) == 8 and s["weekly"][-1] == 1
    assert "email" not in r.text and "광고" not in r.text  # 내용·이메일은 담지 않는다


def _clear_install_sources() -> None:
    from app.features.acquisition.models import InstallSource

    with SessionLocal() as db:
        db.query(InstallSource).delete()
        db.commit()


def test_analytics_acquisition_by_source(client, make_admin):
    """유입 경로: 경로별 가입 수·비율·가족 연결 비율. 기록이 없는 가입자는 unknown 으로 맨 끝에 모인다."""
    _clear_install_sources()
    headers, user_id = _login(client)
    make_admin(user_id)
    url = "/acquisition/install-source"
    yt1, _ = _login(client, "yt_one")
    yt2, _ = _login(client, "yt_two")
    insta, _ = _login(client, "insta_one")
    client.post("/family-group/groups", json={"name": "유튜브 가족"}, headers=yt1)
    for h, body in (
        (yt1, {"source": "youtube", "medium": "video"}),
        (yt2, {"source": "youtube"}),
        (insta, {"source": "instagram", "medium": "sns"}),
    ):
        assert client.post(url, json=body, headers=h).status_code == 204

    d = client.get("/admin/service/analytics", headers=headers).json()
    assert d["acquisition_ready"] is True
    rows = {r["source"]: r for r in d["acquisition"]}
    assert [r["source"] for r in d["acquisition"]][:2] == ["youtube", "instagram"]  # 많은 순
    assert d["acquisition"][-1]["source"] == "unknown"  # 기록 없는 사람은 맨 끝
    assert (rows["youtube"]["signups"], rows["youtube"]["family_rate"]) == (2, 50.0)
    assert (rows["instagram"]["signups"], rows["instagram"]["family_rate"]) == (1, 0.0)
    assert rows["unknown"]["signups"] == d["users"] - 3
    assert sum(r["signups"] for r in d["acquisition"]) == d["users"]
    assert rows["youtube"]["share"] == round(2 * 100 / d["users"], 1)
    assert "yt_one" not in str(d["acquisition"]) and user_id not in str(d["acquisition"])  # 숫자만


def test_analytics_without_acquisition_table(client, make_admin, monkeypatch):
    """유입 경로 표가 아직 없는 DB: 이 구역만 비고(acquisition_ready=false) 나머지 분석은 200 이다."""
    from app.features.service_admin import analytics

    headers, user_id = _login(client)
    make_admin(user_id)
    real = analytics.monitor.status()

    class _NotReady:
        def feature_ready(self, feature: str) -> bool:
            return feature != "acquisition" and real.feature_ready(feature)

    monkeypatch.setattr(analytics.monitor, "status", lambda: _NotReady())
    called = []
    monkeypatch.setattr(analytics.repository, "install_sources", lambda db: called.append(1))
    r = client.get("/admin/service/analytics", headers=headers)
    assert r.status_code == 200, r.text
    assert (r.json()["acquisition_ready"], r.json()["acquisition"]) == (False, [])
    assert called == []  # 없는 표는 읽지 않는다


def test_acquisition_order_and_rates():
    """계산만: 많은 순, 같으면 이름순, unknown 은 개수와 상관없이 맨 끝. 가입자 목록에 없는 기록은 무시한다."""
    from app.features.service_admin.analytics import acquisition

    now = datetime.now(UTC)
    users = {u: now for u in ("a", "b", "c", "d", "e", "f")}
    sources = [("a", "news"), ("b", "blog"), ("c", "blog"), ("gone", "youtube")]
    rows = acquisition(users, sources, first_family={"b": now})
    assert [(r.source, r.signups) for r in rows] == [("blog", 2), ("news", 1), ("unknown", 3)]
    assert rows[0].family_rate == 50.0 and rows[0].share == 33.3
    assert acquisition({}, [], {}) == []


def test_analytics_is_admin_only(client, make_admin):
    headers, _ = _login(client)
    assert client.get("/admin/service/analytics").status_code == 401
    assert _denied(client.get("/admin/service/analytics", headers=headers))


def test_ops_tab_page_is_served(client):
    """'운영 › 서버 상태' 탭이 띄우는 운영 화면 파일(static/ops/)이 서비스 관리자 화면 아래에 있다.
    로그인 없이 받는 정적 파일이고, 데이터는 화면이 토큰으로 /admin/ops/* 를 불러야 나온다."""
    page = client.get("/admin/service/ui/ops/")
    assert page.status_code == 200
    assert 'src="js/embed.js' in page.text
    assert "connect-src 'self'" in page.text  # 같은 출처(API 서버)만 부른다
    for path in ("ops/js/embed.js", "ops/js/app.js", "ops/js/api.js", "ops/css/style.css"):
        assert client.get(f"/admin/service/ui/{path}").status_code == 200, path
    assert 'class="ops-frame"' in client.get("/admin/service/ui/app.js").text


def test_names_are_masked_to_first_letter(client, make_admin):
    """회원·가족 목록의 이름·아이디는 서버에서 첫 글자만 남기고 가려 보낸다(응답 원문에 원래 값이 없다)."""
    headers, user_id = _login(client)
    make_admin(user_id)
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    members = client.get("/admin/service/members", headers=headers)
    me = next(r for r in members.json()["rows"] if r["id"] == user_id)
    assert (me["name"], me["login_id"]) == ("김**", "j********")
    groups = client.get("/admin/service/groups", headers=headers)
    assert groups.json()["rows"][0]["owner_name"] == "김**"
    for r in (members, groups):
        assert "김지민" not in r.text and "jimin_kim" not in r.text and "우리 가족" not in r.text
    # 로그인한 관리자 본인 정보(/me)는 가리지 않는다
    assert client.get("/admin/service/me", headers=headers).json()["name"] == "김지민"


def test_mask_first_rules():
    from app.shared.name_mask import mask_first

    assert mask_first("김준하") == "김**"
    assert mask_first("보경") == "보*"
    assert mask_first("a") == "a"
    assert mask_first("") == "" and mask_first(None) is None
    assert mask_first("(가족 없음)") == "(가족 없음)"  # 안내 문구는 그대로
