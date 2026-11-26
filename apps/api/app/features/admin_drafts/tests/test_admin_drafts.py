"""관리자 AI 초안: 꺼짐, 공지 초안(알림 근거·중복·간격), 답변 초안(가린 글만 보냄·한 번에 5개), 자동 공지(정해 둔 문구·6시간 한 번),
알림 점검 뒤 후속 작업, 권한, 상태 바꾸기, Claude 실패. 가짜 계정·가짜 Claude 만 쓴다."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, select

from app.features.admin_alerts.models import AdminAlertLog
from app.features.admin_drafts import service
from app.features.admin_drafts.models import AdminDraft
from app.shared.config import settings
from app.shared.db import Base, SessionLocal
from app.shared.llm import client as llm

SIGNUP = "/family-group/auth/signup"
LOGIN = "/family-group/auth/login"
PASSWORD = "Sunny-day-2026"
LIST = "/admin/service/drafts"
RUN = "/admin/service/drafts/run"
PHONE = "010-1234-5678"
EMAIL = "hong.gildong@example.com"


def _member(client, login_id: str) -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "시험",
    }
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(LOGIN, json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture(autouse=True)
def _clean(client):
    with SessionLocal() as db:
        db.execute(delete(AdminDraft))
        db.execute(delete(AdminAlertLog))
        for name in ("support_tickets", "notices"):
            db.execute(delete(Base.metadata.tables[name]))
        db.commit()
    yield


@pytest.fixture
def admin(client, monkeypatch) -> tuple[dict, str]:
    headers, user_id = _member(client, f"drafts_admin_{uuid.uuid4().hex[:6]}")
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    return headers, user_id


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "admin_drafts_enabled", True)


@pytest.fixture
def fake(monkeypatch):
    """가짜 Claude: 받은 글을 적어 두고, 공지·답변 모양에 맞는 답을 돌려준다."""
    seen: list[dict] = []

    def complete_json(prompt, schema, system=None, **_kw):
        seen.append({"prompt": prompt, "system": system})
        if "needed" in schema["properties"]:
            data = {
                "needed": True,
                "category": "maintenance",
                "title": "일부 기능 지연 안내",
                "body": "지금 일부 기능이 느려 확인하고 있어요.",
                "reason": "서버 오류율 긴급 알림",
            }
        else:
            data = {
                "topic": "사용법",
                "answer": "문의 주셔서 감사해요. 확인한 뒤 다시 안내해 드릴게요.",
                "reason": "일정 공유 방법 문의",
            }
        return llm.JsonResult(data=data, input_tokens=1, output_tokens=1, model="fake")

    monkeypatch.setattr(service.llm, "complete_json", complete_json)
    return seen


def _alert(severity="긴급", rule="server_error_rate", minutes=5, key=None):
    with SessionLocal() as db:
        db.add(
            AdminAlertLog(
                key=key or f"{rule}:{uuid.uuid4().hex[:6]}",
                rule=rule,
                severity=severity,
                message="최근 60분 요청 200건 중 5xx 40건(20.0%)",
                menu="운영 › 서버 상태",
                created_at=datetime.now(UTC) - timedelta(minutes=minutes),
            )
        )
        db.commit()


def _ticket(user_id: str, title="일정 공유", body=None, kind="inquiry", status="new"):
    tid = uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        db.execute(
            insert(Base.metadata.tables["support_tickets"]).values(
                id=tid,
                user_id=user_id,
                group_id=None,
                kind=kind,
                title=title,
                body=body
                or f"제 번호는 {PHONE} 이고 메일은 {EMAIL} 이에요. 일정 공유는 어떻게 해요?",
                status=status,
                answer=None,
                answered_at=None,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
    return tid


def _drafts(kind=None) -> list[AdminDraft]:
    with SessionLocal() as db:
        q = select(AdminDraft)
        if kind:
            q = q.where(AdminDraft.kind == kind)
        return list(db.scalars(q))


def test_off_does_nothing(client, admin, fake):
    _alert()
    r = client.post(RUN, headers=admin[0])
    assert r.status_code == 200 and r.json() == {
        "enabled": False,
        "notices": 0,
        "replies": 0,
        "published": 0,
    }
    assert fake == [] and _drafts() == []


def test_only_admin(client, admin, on):
    other, _ = _member(client, "drafts_member")
    assert client.get(LIST, headers=other).status_code == 403
    assert client.post(RUN, headers=other).status_code == 403
    assert client.get(LIST).status_code == 401


def test_notice_draft_from_alert_once(client, admin, on, fake):
    _alert()
    r = client.post(RUN, headers=admin[0]).json()
    assert r["notices"] == 1
    assert "5xx 40건" in fake[0]["prompt"] and "운영 › 서버 상태" in fake[0]["prompt"]
    # 같은 알림으로 다시 돌려도 새로 만들지 않는다
    assert client.post(RUN, headers=admin[0]).json()["notices"] == 0
    listed = client.get(LIST, headers=admin[0]).json()
    notice = next(d for d in listed["pending"] if d["kind"] == "notice")
    assert notice["title"] == "일부 기능 지연 안내" and notice["category"] == "maintenance"
    assert notice["reason"] and notice["auto"] is False
    # 초안만 만들고 공지는 올리지 않는다
    with SessionLocal() as db:
        assert db.execute(select(Base.metadata.tables["notices"])).first() is None


def test_notice_draft_waits_six_hours(client, admin, on, fake):
    _alert(key="server_error_rate:a")
    client.post(RUN, headers=admin[0])
    _alert(key="server_error_rate:b")  # 새 알림이 생겨도 6시간 안에는 새 공지 초안을 만들지 않는다
    assert client.post(RUN, headers=admin[0]).json()["notices"] == 0


def test_no_alert_no_notice_and_not_needed_is_hidden(client, admin, on, fake, monkeypatch):
    assert client.post(RUN, headers=admin[0]).json()["notices"] == 0
    assert fake == []

    def not_needed(prompt, schema, system=None, **_kw):
        return llm.JsonResult(
            data={
                "needed": False,
                "category": "info",
                "title": "",
                "body": "",
                "reason": "주의 한 건뿐",
            },
            input_tokens=1,
            output_tokens=1,
            model="fake",
        )

    monkeypatch.setattr(service.llm, "complete_json", not_needed)
    _alert(severity="주의")
    assert client.post(RUN, headers=admin[0]).json()["notices"] == 0
    assert client.get(LIST, headers=admin[0]).json()["pending"] == []
    assert [d.status for d in _drafts("notice")] == [
        "dismissed"
    ]  # 같은 알림으로 다시 묻지 않게 기록만 남긴다


def test_reply_drafts_send_masked_text_only(client, admin, on, fake):
    _, user_id = admin
    tid = _ticket(user_id)
    _ticket(user_id, status="done")  # 끝난 문의는 초안을 만들지 않는다
    r = client.post(RUN, headers=admin[0]).json()
    assert r["replies"] == 1
    sent = fake[0]["prompt"]
    assert PHONE not in sent and "hong.gildong@" not in sent
    assert "일정 공유" in sent and user_id not in sent and "시험" not in sent
    draft = next(
        d for d in client.get(LIST, headers=admin[0]).json()["pending"] if d["kind"] == "reply"
    )
    assert draft["ticket_id"] == tid and draft["title"] == "사용법"
    # 답변 초안을 만들어도 문의에는 답변이 저장되지 않는다
    with SessionLocal() as db:
        t = Base.metadata.tables["support_tickets"]
        assert db.execute(select(t.c.answer, t.c.status).where(t.c.id == tid)).one() == (
            None,
            "new",
        )
    assert (
        client.post(RUN, headers=admin[0]).json()["replies"] == 0
    )  # 같은 문의로 다시 만들지 않는다


def test_reply_batch_limit(client, admin, on, fake):
    for i in range(service.REPLY_BATCH + 2):
        _ticket(admin[1], title=f"문의 {i}")
    assert client.post(RUN, headers=admin[0]).json()["replies"] == service.REPLY_BATCH
    assert client.post(RUN, headers=admin[0]).json()["replies"] == 2


def test_claude_failure_keeps_going(client, admin, on, monkeypatch):
    def boom(*_a, **_kw):
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(service.llm, "complete_json", boom)
    _alert()
    _ticket(admin[1])
    r = client.post(RUN, headers=admin[0])
    assert r.status_code == 200 and r.json()["notices"] == 0 and r.json()["replies"] == 0
    assert _drafts() == []


def test_auto_notice_fixed_text_once(client, admin, fake, monkeypatch):
    monkeypatch.setattr(settings, "auto_notice_enabled", True)
    _alert()
    r = client.post(RUN, headers=admin[0]).json()
    assert r["published"] == 1 and fake == []  # 자동 공지는 AI 를 쓰지 않는다
    with SessionLocal() as db:
        rows = db.execute(select(Base.metadata.tables["notices"])).all()
    assert (
        len(rows) == 1 and rows[0].title == service.AUTO_TITLE and rows[0].category == "maintenance"
    )
    assert "확인하고 있어요" in rows[0].body
    _alert(key="server_error_rate:again")
    assert client.post(RUN, headers=admin[0]).json()["published"] == 0  # 6시간에 한 번
    listed = client.get(LIST, headers=admin[0]).json()
    assert listed["auto_notices"][0]["notice_id"] == rows[0].id and listed["pending"] == []


def test_auto_notice_only_for_recent_urgent_server_rule(client, admin, fake, monkeypatch):
    monkeypatch.setattr(settings, "auto_notice_enabled", True)
    _alert(severity="주의")
    _alert(rule="ai_usage_spike")
    _alert(minutes=120)  # 1시간보다 오래된 긴급 알림
    assert client.post(RUN, headers=admin[0]).json()["published"] == 0


def test_status_change_and_404(client, admin, on, fake):
    _ticket(admin[1])
    client.post(RUN, headers=admin[0])
    draft_id = client.get(LIST, headers=admin[0]).json()["pending"][0]["id"]
    assert (
        client.post(
            f"{LIST}/{draft_id}/status", json={"status": "used"}, headers=admin[0]
        ).status_code
        == 204
    )
    assert client.get(LIST, headers=admin[0]).json()["pending"] == []
    assert (
        client.post(f"{LIST}/nope/status", json={"status": "used"}, headers=admin[0]).status_code
        == 404
    )
    assert (
        client.post(
            f"{LIST}/{draft_id}/status", json={"status": "pending"}, headers=admin[0]
        ).status_code
        == 422
    )


def test_runs_after_alert_checks(client, admin, on, fake, monkeypatch):
    monkeypatch.setattr(settings, "admin_alerts_enabled", True)
    monkeypatch.setattr(settings, "admin_alerts_token", "tok")
    _ticket(admin[1])
    r = client.post("/internal/alerts/run", headers={"X-Alert-Token": "tok"})
    assert r.status_code == 200
    assert len(_drafts("reply")) == 1  # 점검이 끝난 뒤 후속 작업으로 초안을 만든다


def test_make_reply_for_one_ticket_any_status(client, admin, on, fake):
    tid = _ticket(admin[1], status="working")  # 처리 중인 문의도 바로 만들 수 있다
    r = client.post(f"{LIST}/reply/{tid}", headers=admin[0])
    assert r.status_code == 200, r.text
    assert r.json()["ticket_id"] == tid and r.json()["status"] == "pending"
    assert PHONE not in fake[-1]["prompt"] and "hong.gildong@" not in fake[-1]["prompt"]
    # 버린 뒤 다시 누르면 같은 줄을 새 내용으로 바꿔 다시 대기로 둔다
    client.post(f"{LIST}/{r.json()['id']}/status", json={"status": "dismissed"}, headers=admin[0])
    again = client.post(f"{LIST}/reply/{tid}", headers=admin[0]).json()
    assert again["id"] == r.json()["id"] and again["status"] == "pending"
    assert len(_drafts("reply")) == 1


def test_make_reply_errors(client, admin, fake, monkeypatch):
    tid = _ticket(admin[1])
    assert client.post(f"{LIST}/reply/{tid}", headers=admin[0]).json()["code"] == "drafts_disabled"
    monkeypatch.setattr(settings, "admin_drafts_enabled", True)
    assert client.post(f"{LIST}/reply/nope", headers=admin[0]).status_code == 404

    def boom(*_a, **_kw):
        raise llm.LLMUnavailable("down")

    monkeypatch.setattr(service.llm, "complete_json", boom)
    r = client.post(f"{LIST}/reply/{tid}", headers=admin[0])
    assert r.status_code == 503 and _drafts() == []
    other, _ = _member(client, "drafts_member2")
    assert client.post(f"{LIST}/reply/{tid}", headers=other).status_code == 403


def test_make_notice_from_topic(client, admin, on, fake):
    r = client.post(
        f"{LIST}/notice", json={"topic": f"내일 새벽 점검 문의는 {PHONE}"}, headers=admin[0]
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "notice" and r.json()["status"] == "pending" and r.json()["title"]
    assert "내일 새벽 점검" in fake[-1]["prompt"] and PHONE not in fake[-1]["prompt"]
    with SessionLocal() as db:  # 초안만 만들고 공지는 올리지 않는다
        assert db.execute(select(Base.metadata.tables["notices"])).first() is None


def test_make_notice_needs_topic_or_alert(client, admin, on, fake):
    r = client.post(f"{LIST}/notice", json={"topic": ""}, headers=admin[0])
    assert r.status_code == 422 and r.json()["code"] == "topic_required" and fake == []
    _alert()
    assert client.post(f"{LIST}/notice", json={}, headers=admin[0]).status_code == 200
    assert "5xx 40건" in fake[-1]["prompt"]


def _scripted(monkeypatch, answers):
    """가짜 Claude: 준비한 답을 차례로 돌려주고 받은 글을 적어 둔다(다시 쓰게 하는지 보려고)."""
    seen: list[str] = []

    def complete_json(prompt, schema, system=None, **_kw):
        seen.append(prompt)
        data = answers[min(len(seen), len(answers)) - 1]
        return llm.JsonResult(data=data, input_tokens=1, output_tokens=1, model="fake")

    monkeypatch.setattr(service.llm, "complete_json", complete_json)
    return seen


def _notice_answer(body, title="점검 안내"):
    return {
        "needed": True,
        "category": "maintenance",
        "title": title,
        "body": body,
        "reason": "주제",
    }


def _reply_answer(answer):
    return {"topic": "결제", "answer": answer, "reason": "환불 문의"}


def test_mask_hides_account_numbers_without_label():
    masked = service._mask("환불 계좌는 국민 123456-78-901234 예요. 2026-11-25 에 결제했어요")
    assert "123456" not in masked and "901234" not in masked
    assert "2026-11-25" in masked  # 날짜처럼 짧은 숫자는 그대로 둔다


def test_notice_rewrites_once_when_numbers_are_made_up(client, admin, on, monkeypatch):
    seen = _scripted(
        monkeypatch,
        [
            _notice_answer("내일 새벽 2시부터 4시까지 점검이 있어요."),  # 주제에 없는 시각을 지어냄
            _notice_answer("내일 새벽에 점검이 있어요."),
        ],
    )
    r = client.post(f"{LIST}/notice", json={"topic": "내일 새벽 점검"}, headers=admin[0])
    assert r.status_code == 200, r.text
    assert len(seen) == 2 and "없는 숫자" in seen[1]
    assert r.json()["body"] == "내일 새벽에 점검이 있어요."


def test_notice_drops_weekday_and_restores_admin_contact(client, admin, on, monkeypatch):
    seen = _scripted(
        monkeypatch,
        [_notice_answer("11월 27일(목) 점검이 있어요. 문의는 010-****-**** 로 해 주세요.")],
    )
    topic = f"11월 27일 점검, 문의는 {PHONE}"
    r = client.post(f"{LIST}/notice", json={"topic": topic}, headers=admin[0])
    assert r.status_code == 200, r.text
    assert PHONE not in seen[0]  # Claude 에는 가린 번호만 간다
    body = r.json()["body"]
    assert "(목)" not in body and PHONE in body  # 요일은 지우고, 관리자가 적은 연락처는 되돌린다
    assert "오늘 날짜" in seen[0] and "지금 시각" not in seen[0]


def test_reply_rewrites_once_and_never_keeps_masked_name(client, admin, on, monkeypatch):
    tid = _ticket(admin[1])
    seen = _scripted(
        monkeypatch,
        [
            _reply_answer("김** 회원님, that 문제는 확인한 뒤 안내해 드릴게요."),
            _reply_answer("김** 회원님, 문의 주셔서 감사해요. 확인한 뒤 안내해 드릴게요."),
        ],
    )
    r = client.post(f"{LIST}/reply/{tid}", headers=admin[0])
    assert r.status_code == 200, r.text
    assert len(seen) == 2 and "고칠 점" in seen[1]
    assert "that" not in r.json()["body"] and "김**" not in r.json()["body"]
    assert r.json()["body"].startswith("회원님")


def test_reply_system_includes_app_guide(client, admin, on, fake):
    tid = _ticket(admin[1])
    assert client.post(f"{LIST}/reply/{tid}", headers=admin[0]).status_code == 200
    assert "앱 안내 자료" in fake[-1]["system"] and "비밀번호 찾기" in fake[-1]["system"]
