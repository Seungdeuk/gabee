"""이메일 인증과 비밀번호 재설정(메일은 가짜 발송기로 가로채서 확인한다 — 실제 메일을 보내지 않는다)."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.features.family_group import service
from app.features.family_group.models import EmailVerification, PasswordReset, RefreshToken, User
from app.shared import mailer, tokens
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

SIGNUP, LOGIN, REFRESH = (
    "/family-group/auth/signup",
    "/family-group/auth/login",
    "/family-group/auth/refresh",
)
VERIFY_REQ = "/family-group/auth/email/verify/request"
VERIFY_CONFIRM = "/family-group/auth/email/verify/confirm"
RESET_REQ = "/family-group/auth/password/reset/request"
RESET_CONFIRM = "/family-group/auth/password/reset/confirm"
ME = "/family-group/auth/me"
PASSWORD = "Sunny-day-2026"
NEW_PASSWORD = "Brand-new-pass-77"


class Outbox:
    """메일 발송기 대역: 보내지 않고 모아 둔다."""

    def __init__(self, fail=False):
        self.mails: list[mailer.Mail] = []
        self.tokens: list[str] = []
        self.fail = fail

    def send(self, mail):
        if self.fail:
            raise mailer.MailSendError("boom")
        self.mails.append(mail)

    def watch(self, monkeypatch) -> "Outbox":
        """메일에는 토큰(링크)이 없으므로, 서버가 메일용으로 발급한 토큰을 발급 시점에 따로 모아 둔다."""
        real = service._new_token_row

        def spy(*args, **kwargs):
            token, code, row = real(*args, **kwargs)
            self.tokens.append(token)
            return token, code, row

        monkeypatch.setattr(service, "_new_token_row", spy)
        return self

    def last_token(self) -> str:
        return self.tokens[-1]


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox().watch(monkeypatch)
    mailer.set_mailer(box)
    return box


def register(client, login_id="jimin_kim", email="jimin@example.com"):
    r = client.post(
        SIGNUP, json={"login_id": login_id, "password": PASSWORD, "email": email, "name": "지민"}
    )
    assert r.status_code == 201, r.text
    return r.json()["user"]


def login(client, login_id="jimin_kim", password=PASSWORD):
    return client.post(LOGIN, json={"login_id": login_id, "password": password})


def bearer_for(client, login_id="jimin_kim") -> dict:
    return {"Authorization": f"Bearer {login(client, login_id).json()['access_token']}"}


def db_user(login_id="jimin_kim") -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.login_id == login_id))


# ---------- 이메일 인증 ----------
def test_verification_flow_sends_a_one_time_token_and_verifies(client, outbox):
    register(client)
    headers = bearer_for(client)
    assert client.post(VERIFY_REQ, headers=headers).status_code == 204
    (mail,) = outbox.mails
    assert mail.to == "jimin@example.com" and "token=" not in mail.body  # 링크 없음
    token = outbox.last_token()

    assert client.get(ME, headers=headers).json()["email_verified"] is False
    r = client.post(VERIFY_CONFIRM, json={"token": token})  # 로그인 없이도 토큰만으로 가능
    assert r.status_code == 200 and r.json() == {"email_verified": True}
    assert client.get(ME, headers=headers).json()["email_verified"] is True
    assert db_user().email_verified_at is not None


def test_token_is_stored_only_as_a_hash_and_cannot_be_read_back(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    token = outbox.last_token()
    with SessionLocal() as db:
        (row,) = db.scalars(select(EmailVerification)).all()
    assert row.token_hash == tokens.hash_refresh_token(token) and token not in row.token_hash
    assert row.email == "jimin@example.com" and row.verified_at is None


def test_token_is_single_use(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    token = outbox.last_token()
    assert client.post(VERIFY_CONFIRM, json={"token": token}).status_code == 200
    again = client.post(VERIFY_CONFIRM, json={"token": token})
    assert again.status_code == 400 and again.json()["code"] == "verification_used"


def test_unknown_and_expired_tokens_are_rejected(client, outbox):
    register(client)
    assert (
        client.post(VERIFY_CONFIRM, json={"token": "nope"}).json()["code"] == "verification_invalid"
    )
    client.post(VERIFY_REQ, headers=bearer_for(client))
    token = outbox.last_token()
    with SessionLocal() as db:
        row = db.scalar(select(EmailVerification))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    r = client.post(VERIFY_CONFIRM, json={"token": token})
    assert r.status_code == 400 and r.json()["code"] == "verification_expired"
    assert db_user().email_verified_at is None


def test_resend_invalidates_the_previous_link(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    first = outbox.last_token()
    client.post(VERIFY_REQ, headers=headers)
    second = outbox.last_token()
    assert first != second and len(outbox.mails) == 2
    assert client.post(VERIFY_CONFIRM, json={"token": first}).status_code == 400  # 이전 링크는 무효
    assert client.post(VERIFY_CONFIRM, json={"token": second}).status_code == 200


def test_resend_is_rate_limited_by_cooldown_and_hourly_cap(client, outbox, monkeypatch):
    register(client)
    headers = bearer_for(client)
    assert client.post(VERIFY_REQ, headers=headers).status_code == 204
    blocked = client.post(VERIFY_REQ, headers=headers)  # 재발송 간격(60초) 안
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_requests"
    assert int(blocked.headers["Retry-After"]) >= 1 and len(outbox.mails) == 1

    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "verify_max_per_hour", 3)
    service.mail_limiter.reset()
    codes = [client.post(VERIFY_REQ, headers=headers).status_code for _ in range(5)]
    assert codes == [204, 204, 204, 429, 429] and len(outbox.mails) == 4


def test_request_requires_login_and_a_real_email_account(client, outbox):
    assert client.post(VERIFY_REQ).status_code == 401
    anonymous = signup(client, "익명")
    assert client.post(VERIFY_REQ, headers=anonymous).status_code == 401  # Bearer 전용
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    client.post(VERIFY_CONFIRM, json={"token": outbox.last_token()})
    done = client.post(VERIFY_REQ, headers=headers)
    assert done.status_code == 409 and done.json()["code"] == "email_already_verified"
    assert len(outbox.mails) == 1


def test_without_mail_configuration_nothing_is_reported_as_sent(client):
    register(client)
    headers = bearer_for(client)
    for r in (
        client.post(VERIFY_REQ, headers=headers),
        client.post(RESET_REQ, json={"login_id": "jimin_kim", "email": "jimin@example.com"}),
    ):
        assert r.status_code == 503 and r.json()["code"] == "mail_not_configured"
    with SessionLocal() as db:
        assert db.scalars(select(EmailVerification)).all() == []  # 토큰도 만들지 않았다
        assert db.scalars(select(PasswordReset)).all() == []


def test_send_failure_is_reported_for_verification(client):
    mailer.set_mailer(Outbox(fail=True))
    register(client)
    r = client.post(VERIFY_REQ, headers=bearer_for(client))
    assert r.status_code == 503 and r.json()["code"] == "mail_send_failed"


def test_console_backend_is_dev_only_and_smtp_needs_host_and_from(client, monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "console")
    assert isinstance(mailer.get_mailer(), mailer.ConsoleMailer)  # 테스트 DB 는 SQLite
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u@db/gabee")
    monkeypatch.setattr(settings, "debug", False)
    assert (
        mailer.get_mailer() is None
    )  # 공용·운영 DB 에서는 로그로 토큰을 남기는 백엔드를 쓰지 않는다
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    assert mailer.get_mailer() is None  # SMTP_HOST/SMTP_FROM 없음
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "no-reply@example.com")
    assert isinstance(mailer.get_mailer(), mailer.SmtpMailer)


def test_smtp_mailer_uses_settings_and_never_logs_the_body(monkeypatch, caplog):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["conn"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls["tls"] = True

        def login(self, user, password):
            calls["login"] = (user, password)

        def send_message(self, msg):
            calls["msg"] = msg

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    for k, v in dict(
        smtp_host="h", smtp_port=2525, smtp_user="u", smtp_password="p", smtp_from="a@b.co"
    ).items():
        monkeypatch.setattr(settings, k, v)
    mailer.SmtpMailer().send(mailer.Mail(to="x@y.com", subject="s", body="본문 토큰 abc"))
    assert calls["conn"][:2] == ("h", 2525) and calls["tls"] and calls["login"] == ("u", "p")
    assert calls["msg"]["To"] == "x@y.com" and calls["msg"]["From"] == "a@b.co"


def _capture_smtp(monkeypatch) -> dict:
    calls: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, user, password):
            pass

        def send_message(self, msg):
            calls["msg"] = msg

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    for k, v in dict(smtp_host="h", smtp_user="u", smtp_password="p", smtp_from="a@b.co").items():
        monkeypatch.setattr(settings, k, v)
    return calls


def test_html_mail_embeds_the_mascot_and_keeps_a_plain_text_part(monkeypatch):
    calls = _capture_smtp(monkeypatch)
    html = f'<img src="cid:{mailer.MASCOT_CID}"><b>123456</b>'
    mailer.SmtpMailer().send(mailer.Mail(to="x@y.com", subject="s", body="코드 123456", html=html))
    msg = calls["msg"]
    assert msg.get_body(("plain",)).get_content().strip() == "코드 123456"
    assert "123456" in msg.get_body(("html",)).get_content()
    (image,) = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert (
        image["Content-ID"] == f"<{mailer.MASCOT_CID}>"
        and image.get_payload(decode=True)[:4] == b"\x89PNG"
    )


def test_plain_mail_has_no_html_or_image(monkeypatch):
    calls = _capture_smtp(monkeypatch)
    mailer.SmtpMailer().send(mailer.Mail(to="x@y.com", subject="s", body="본문"))
    msg = calls["msg"]
    assert msg.get_content_type() == "text/plain"
    assert not any(p.get_content_type() == "image/png" for p in msg.walk())


def test_mail_still_goes_out_without_the_mascot_file(monkeypatch):
    calls = _capture_smtp(monkeypatch)
    monkeypatch.setattr(mailer, "_mascot_png", lambda: None)
    html = f'<img src="cid:{mailer.MASCOT_CID}">코드'
    mailer.SmtpMailer().send(mailer.Mail(to="x@y.com", subject="s", body="코드", html=html))
    assert not any(p.get_content_type() == "image/png" for p in calls["msg"].walk())


def test_smtp_failure_is_wrapped_without_leaking_details(monkeypatch, caplog):
    import smtplib

    def boom(*a, **k):
        raise smtplib.SMTPAuthenticationError(535, b"secret-password-in-error")

    monkeypatch.setattr("smtplib.SMTP", boom)
    monkeypatch.setattr(settings, "smtp_host", "h")
    monkeypatch.setattr(settings, "smtp_from", "a@b.co")
    with pytest.raises(mailer.MailSendError):
        mailer.SmtpMailer().send(
            mailer.Mail(to="victim@example.com", subject="s", body="token-abc")
        )
    assert (
        "secret-password" not in caplog.text
        and "victim@example.com" not in caplog.text
        and "token-abc" not in caplog.text
    )


def test_concurrent_confirmations_only_one_succeeds(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    token = outbox.last_token()
    results, barrier = [], threading.Barrier(6)

    def go():
        barrier.wait()
        results.append(client.post(VERIFY_CONFIRM, json={"token": token}).status_code)

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200] + [400] * 5, results


# ---------- 미인증 계정 권한 정책 ----------
def test_unverified_member_cannot_create_or_join_a_family_when_the_policy_is_on(
    client, outbox, monkeypatch
):
    monkeypatch.setattr(settings, "require_email_verification", True)  # 선택 정책(기본은 꺼짐)
    owner = signup(client, "주인")
    group = client.post("/family-group/groups", json={"name": "가족"}, headers=owner).json()
    register(client)
    headers = bearer_for(client)
    assert client.get(ME, headers=headers).status_code == 200  # 내 정보 조회는 허용
    for r in (
        client.post("/family-group/groups", json={"name": "x"}, headers=headers),
        client.post(
            "/family-group/groups/join", json={"code": group["invite_code"]}, headers=headers
        ),
    ):
        assert r.status_code == 403 and r.json()["code"] == "email_not_verified"
    client.post(VERIFY_REQ, headers=headers)
    client.post(VERIFY_CONFIRM, json={"token": outbox.last_token()})
    joined = client.post(
        "/family-group/groups/join", json={"code": group["invite_code"]}, headers=headers
    )
    assert joined.status_code == 200 and joined.json()["status"] == "pending"


def test_without_mail_configuration_the_policy_does_not_block_new_members(client, monkeypatch):
    """SMTP 가 없으면 인증할 방법이 없으므로 정책을 켜 두어도 가입 후 막다른 길이 되지 않는다."""
    monkeypatch.setattr(settings, "require_email_verification", True)
    register(client)
    headers = bearer_for(client)
    assert client.post(VERIFY_REQ, headers=headers).status_code == 503  # 인증 메일은 못 보낸다
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=headers).status_code
        == 201
    )


def test_policy_applies_when_it_is_on_and_mail_is_configured(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)
    register(client)
    r = client.post("/family-group/groups", json={"name": "가족"}, headers=bearer_for(client))
    assert r.status_code == 403 and r.json()["code"] == "email_not_verified"


def test_anonymous_accounts_are_not_affected_by_the_verification_policy(client):
    headers = signup(client, "익명")  # 기존 모바일 앱 방식
    assert (
        client.post("/family-group/groups", json={"name": "가족"}, headers=headers).status_code
        == 201
    )
    other = signup(client, "다른 익명")
    code = client.get("/family-group/groups/me", headers=headers).json()["invite_code"]
    joined = client.post("/family-group/groups/join", json={"code": code}, headers=other)
    assert joined.status_code == 200 and joined.json()["status"] == "pending"  # 익명도 승인 대기


def test_unverified_members_can_create_a_family_by_default(client, outbox):
    """기본 설정: 메일이 설정돼 있어도 이메일을 인증하지 않은 회원이 가족을 만들고 참여할 수 있다."""
    register(client)
    r = client.post("/family-group/groups", json={"name": "가족"}, headers=bearer_for(client))
    assert r.status_code == 201


# ---------- 비밀번호 재설정 ----------
def request_reset(client, email="jimin@example.com", login_id="jimin_kim"):
    return client.post(RESET_REQ, json={"login_id": login_id, "email": email})


def test_reset_flow_changes_the_password_and_logs_out_every_session(client, outbox):
    register(client)
    phone, tablet = login(client).json(), login(client).json()
    assert request_reset(client).status_code == 204
    (mail,) = outbox.mails
    assert mail.to == "jimin@example.com" and "token=" not in mail.body  # 링크 없음
    token = outbox.last_token()

    r = client.post(RESET_CONFIRM, json={"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 204
    assert login(client, password=PASSWORD).status_code == 401  # 이전 비밀번호는 못 쓴다
    assert login(client, password=NEW_PASSWORD).status_code == 200
    for session in (phone, tablet):  # 기존 Refresh Token 전부 폐기
        assert (
            client.post(REFRESH, json={"refresh_token": session["refresh_token"]}).status_code
            == 401
        )
    assert (
        db_user().password_hash.startswith("$argon2id$")
        and NEW_PASSWORD not in db_user().password_hash
    )


def test_reset_token_is_hashed_single_use_and_expires(client, outbox):
    register(client)
    request_reset(client)
    token = outbox.last_token()
    with SessionLocal() as db:
        (row,) = db.scalars(select(PasswordReset)).all()
    assert row.token_hash == tokens.hash_refresh_token(token) and row.used_at is None
    ttl = (row.expires_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds()
    assert 0 < ttl <= settings.password_reset_ttl_seconds

    assert (
        client.post(RESET_CONFIRM, json={"token": token, "new_password": NEW_PASSWORD}).status_code
        == 204
    )
    again = client.post(RESET_CONFIRM, json={"token": token, "new_password": "Another-pass-88"})
    assert again.status_code == 400 and again.json()["code"] == "reset_token_used"
    assert login(client, password=NEW_PASSWORD).status_code == 200

    request_reset(client)
    token = outbox.last_token()
    with SessionLocal() as db:
        db.scalars(
            select(PasswordReset).where(PasswordReset.used_at.is_(None))
        ).first().expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = client.post(RESET_CONFIRM, json={"token": token, "new_password": "Another-pass-88"})
    assert expired.json()["code"] == "reset_token_expired"
    assert (
        client.post(RESET_CONFIRM, json={"token": "nope", "new_password": NEW_PASSWORD}).json()[
            "code"
        ]
        == "reset_token_invalid"
    )


def test_new_password_must_follow_the_rules_and_a_weak_one_keeps_the_token(client, outbox):
    register(client)
    request_reset(client)
    token = outbox.last_token()
    for weak in ("short1", "onlyletterspassword", "Jimin_Kim-2026-x"):
        r = client.post(RESET_CONFIRM, json={"token": token, "new_password": weak})
        assert r.status_code == 400 and r.json()["code"] == "weak_password"
    assert (
        client.post(RESET_CONFIRM, json={"token": token, "new_password": NEW_PASSWORD}).status_code
        == 204
    )


def test_request_response_does_not_reveal_whether_the_account_exists(client, outbox):
    register(client)
    anonymous = signup(client, "익명")
    assert anonymous
    known = request_reset(client, "jimin@example.com")
    unknown = request_reset(client, "nobody@example.com")
    assert (
        known.status_code == unknown.status_code == 204 and known.content == unknown.content == b""
    )
    assert (
        len(outbox.mails) == 1 and outbox.mails[0].to == "jimin@example.com"
    )  # 없는 주소로는 메일을 보내지 않는다
    with SessionLocal() as db:
        assert len(db.scalars(select(PasswordReset)).all()) == 1


def test_reset_request_is_rate_limited_per_email_and_per_ip_without_revealing_accounts(
    client, outbox, monkeypatch
):
    register(client)
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 2)
    results = [request_reset(client).status_code for _ in range(4)]
    assert results == [204, 204, 429, 429]
    # 없는 이메일도 똑같이 제한된다(제한 여부로 계정 존재를 알 수 없다)
    ghost = [request_reset(client, "ghost@example.com").status_code for _ in range(4)]
    assert ghost == [204, 204, 429, 429]
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 100)
    monkeypatch.setattr(settings, "reset_max_per_ip_per_hour", 3)
    service.mail_limiter.reset()
    mixed = [request_reset(client, f"user{i}@example.com").status_code for i in range(5)]
    assert mixed == [204, 204, 204, 429, 429]


def test_newer_reset_link_invalidates_older_ones(client, outbox):
    register(client)
    request_reset(client)
    old = outbox.last_token()
    request_reset(client)
    new = outbox.last_token()
    assert (
        client.post(RESET_CONFIRM, json={"token": old, "new_password": NEW_PASSWORD}).status_code
        == 400
    )
    assert (
        client.post(RESET_CONFIRM, json={"token": new, "new_password": NEW_PASSWORD}).status_code
        == 204
    )


def test_concurrent_reset_confirmations_only_one_wins_and_sessions_end_revoked(client, outbox):
    register(client)
    session = login(client).json()
    request_reset(client)
    token = outbox.last_token()
    results, barrier = [], threading.Barrier(5)

    def go(i):
        barrier.wait()
        results.append(
            client.post(
                RESET_CONFIRM, json={"token": token, "new_password": f"Brand-new-pass-{i}0"}
            ).status_code
        )

    threads = [threading.Thread(target=go, args=(i,)) for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [204] + [400] * 4, results
    assert client.post(REFRESH, json={"refresh_token": session["refresh_token"]}).status_code == 401
    with SessionLocal() as db:
        assert all(r.revoked_at is not None for r in db.scalars(select(RefreshToken)))


def test_password_reset_invalidates_existing_access_tokens_immediately(client, outbox):
    register(client)
    old_access = login(client).json()["access_token"]
    old = {"Authorization": f"Bearer {old_access}"}
    assert client.get(ME, headers=old).status_code == 200
    request_reset(client)
    client.post(RESET_CONFIRM, json={"token": outbox.last_token(), "new_password": NEW_PASSWORD})
    stale = client.get(ME, headers=old)  # 만료(15분)를 기다리지 않고 바로 거부
    assert stale.status_code == 401 and stale.json()["code"] == "token_invalid"
    assert client.get("/family-group/me", headers=old).status_code == 401
    fresh = {
        "Authorization": f"Bearer {login(client, password=NEW_PASSWORD).json()['access_token']}"
    }
    assert client.get(ME, headers=fresh).status_code == 200


def test_other_users_access_tokens_survive_someones_password_reset(client, outbox):
    register(client)
    register(client, "other_user", "other@example.com")
    other = bearer_for(client, "other_user")
    request_reset(client)
    client.post(RESET_CONFIRM, json={"token": outbox.last_token(), "new_password": NEW_PASSWORD})
    assert client.get(ME, headers=other).status_code == 200


def test_background_send_failure_is_logged_but_the_response_stays_uniform(client, caplog):
    mailer.set_mailer(Outbox(fail=True))
    register(client)
    with caplog.at_level("ERROR"):
        known = request_reset(client, "jimin@example.com")
        unknown = request_reset(client, "ghost@example.com")
    assert known.status_code == unknown.status_code == 204 and known.content == unknown.content
    failures = [r.getMessage() for r in caplog.records if "mail_delivery_failed" in r.getMessage()]
    assert failures == [
        "mail_delivery_failed kind=password_reset reason=boom"
    ]  # 존재하는 계정 1건만 시도·기록
    assert "jimin@example.com" not in caplog.text and "token" not in caplog.text.lower().replace(
        "kind", ""
    )


def test_unexpected_exception_in_background_send_is_logged_too(client, caplog):
    class Exploding:
        def send(self, mail):
            raise RuntimeError("unexpected")

    mailer.set_mailer(Exploding())
    register(client)
    with caplog.at_level("ERROR"):
        assert request_reset(client).status_code == 204
    assert "mail_delivery_failed kind=password_reset reason=RuntimeError" in caplog.text


def test_successful_reset_also_clears_the_login_lockout(client, outbox):
    register(client)
    request_reset(client)
    for _ in range(settings.login_max_failures_per_id):
        login(client, password="Wrong-pass-1")
    assert login(client).status_code == 429
    client.post(RESET_CONFIRM, json={"token": outbox.last_token(), "new_password": NEW_PASSWORD})
    assert login(client, password=NEW_PASSWORD).status_code == 200


# ---------- 이메일 선점·탈취 시나리오 ----------
def test_reset_proves_mailbox_ownership_so_a_squatted_account_can_be_reclaimed(client, outbox):
    """공격자가 피해자 이메일로 미리 가입(미인증)해 둔 경우: 피해자가 그 이메일로 재설정하면
    공격자의 비밀번호·세션은 사라지고 피해자가 계정을 갖는다."""
    register(client, "attacker_id", "victim@example.com")  # 공격자가 비밀번호 PASSWORD 로 선점
    attacker_session = login(client, "attacker_id").json()
    assert db_user("attacker_id").email_verified_at is None
    request_reset(client, "victim@example.com", "attacker_id")  # 메일은 피해자에게만 간다
    assert outbox.mails[-1].to == "victim@example.com"
    client.post(RESET_CONFIRM, json={"token": outbox.last_token(), "new_password": NEW_PASSWORD})
    assert login(client, "attacker_id", PASSWORD).status_code == 401  # 공격자의 비밀번호 무효
    assert (
        client.post(REFRESH, json={"refresh_token": attacker_session["refresh_token"]}).status_code
        == 401
    )
    assert login(client, "attacker_id", NEW_PASSWORD).status_code == 200
    assert db_user("attacker_id").email_verified_at is not None


def test_attacker_cannot_verify_someone_elses_email_or_use_someone_elses_token(client, outbox):
    register(client, "victim_id", "victim@example.com")
    register(client, "attacker_id", "attacker@example.com")
    client.post(VERIFY_REQ, headers=bearer_for(client, "victim_id"))
    victim_token = outbox.last_token()
    assert outbox.mails[-1].to == "victim@example.com"  # 인증 메일은 계정에 등록된 주소로만 간다
    # 요청 본문으로 받는 주소가 없어서 공격자가 다른 주소로 메일을 보내게 만들 수 없다
    assert (
        client.post(
            VERIFY_REQ,
            json={"email": "elsewhere@example.com"},
            headers=bearer_for(client, "attacker_id"),
        ).status_code
        == 204
    )
    assert outbox.mails[-1].to == "attacker@example.com"
    # 공격자 계정은 피해자의 토큰으로 인증되지 않는다(토큰은 발급 대상 계정에만 적용)
    client.post(VERIFY_CONFIRM, json={"token": victim_token})
    assert (
        db_user("victim_id").email_verified_at is not None
        and db_user("attacker_id").email_verified_at is None
    )


def test_token_bound_to_an_email_does_not_verify_a_changed_email(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    token = outbox.last_token()
    with SessionLocal() as db:
        db.scalar(select(User).where(User.login_id == "jimin_kim")).email = "changed@example.com"
        db.commit()
    assert (
        client.post(VERIFY_CONFIRM, json={"token": token}).status_code == 200
    )  # 토큰은 소비되지만
    assert db_user().email_verified_at is None  # 바뀐 이메일은 인증되지 않는다


def test_anonymous_and_unknown_emails_get_no_reset_mail(client, outbox):
    signup(client, "익명")
    assert request_reset(client, "anyone@example.com").status_code == 204
    assert outbox.mails == []
    assert (
        client.post(RESET_REQ, json={"login_id": "jimin_kim", "email": "not-an-email"}).status_code
        == 400
    )
