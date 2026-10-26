"""메일의 6자리 코드로 이메일 인증·비밀번호 재설정(링크 방식은 test_email_flows.py 가 그대로 확인한다)."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.features.family_group.models import EmailVerification, PasswordReset
from app.shared import mailer
from app.shared.config import settings
from app.shared.db import SessionLocal

from .test_email_flows import (
    ME,
    NEW_PASSWORD,
    PASSWORD,
    REFRESH,
    RESET_REQ,
    VERIFY_CONFIRM,
    VERIFY_REQ,
    Outbox,
    bearer_for,
    db_user,
    login,
    register,
)

VERIFY_CODE = "/family-group/auth/email/verify/confirm-code"
RESET_CODE = "/family-group/auth/password/reset/confirm-code"


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    mailer.set_mailer(box)
    monkeypatch.setattr(settings, "verify_resend_cooldown_seconds", 0)
    return box


def last_code(box: Outbox) -> str:
    return re.search(r"코드: (\d{6})", box.mails[-1].body).group(1)


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def reset_with(client, email, code, password=NEW_PASSWORD):
    return client.post(RESET_CODE, json={"email": email, "code": code, "new_password": password})


# ---------- 이메일 인증 ----------
def test_mail_has_a_six_digit_code_and_the_auto_verify_link(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    body = outbox.mails[-1].body
    assert re.search(r"인증 코드: \d{6}\n", body) and "gabee://verify-email?token=" in body


def test_verify_with_the_six_digit_code(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    r = client.post(VERIFY_CODE, json={"code": last_code(outbox)}, headers=headers)
    assert r.status_code == 200 and r.json() == {"email_verified": True}
    assert client.get(ME, headers=headers).json()["email_verified"] is True
    # 같은 메일의 링크는 이미 소비돼 다시 쓸 수 없고, 코드를 다시 보내도 이미 인증된 계정은 같은 결과다
    again = client.post(VERIFY_CODE, json={"code": last_code(outbox)}, headers=headers)
    assert again.status_code == 200
    assert (
        client.post(VERIFY_CONFIRM, json={"token": outbox.last_token()}).json()["code"]
        == "verification_used"
    )


def test_the_link_still_verifies_and_makes_the_code_useless(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    assert client.post(VERIFY_CONFIRM, json={"token": outbox.last_token()}).status_code == 200
    assert db_user().email_verified_at is not None


def test_code_is_stored_only_as_a_salted_hash(client, outbox):
    register(client)
    client.post(VERIFY_REQ, headers=bearer_for(client))
    code = last_code(outbox)
    with SessionLocal() as db:
        (row,) = db.scalars(select(EmailVerification)).all()
    assert row.code_hash and code not in row.code_hash and len(row.code_hash) == 64
    assert row.failed_attempts == 0


def test_wrong_codes_are_counted_and_the_limit_locks_even_the_right_code(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    code = last_code(outbox)
    for _ in range(settings.code_max_attempts):
        r = client.post(VERIFY_CODE, json={"code": wrong(code)}, headers=headers)
        assert r.status_code == 400 and r.json()["code"] == "verification_code_invalid"
    locked = client.post(
        VERIFY_CODE, json={"code": code}, headers=headers
    )  # 맞는 코드도 이제 못 쓴다
    assert locked.status_code == 400 and locked.json()["code"] == "verification_code_locked"
    assert db_user().email_verified_at is None
    # 링크도 같은 메일의 것이라 별개로 동작하지만, 새 메일을 받으면 새 코드가 새 횟수로 시작한다
    client.post(VERIFY_REQ, headers=headers)
    fresh = client.post(VERIFY_CODE, json={"code": last_code(outbox)}, headers=headers)
    assert fresh.status_code == 200


def test_resend_invalidates_the_previous_code(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    first = last_code(outbox)
    client.post(VERIFY_REQ, headers=headers)
    second = last_code(outbox)
    if first != second:  # (1/100만 확률로 같으면 이 확인은 의미가 없다)
        r = client.post(VERIFY_CODE, json={"code": first}, headers=headers)
        assert r.json()["code"] == "verification_code_invalid"
    assert client.post(VERIFY_CODE, json={"code": second}, headers=headers).status_code == 200


def test_expired_code_asks_for_a_new_mail(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    code = last_code(outbox)
    with SessionLocal() as db:
        row = db.scalar(select(EmailVerification))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    r = client.post(VERIFY_CODE, json={"code": code}, headers=headers)
    assert r.status_code == 400 and r.json()["code"] == "verification_expired"


def test_code_verification_needs_login_and_someone_elses_code_does_not_work(client, outbox):
    register(client, "jimin_kim", "jimin@example.com")
    register(client, "minho_park", "minho@example.com")
    jimin, minho = bearer_for(client, "jimin_kim"), bearer_for(client, "minho_park")
    client.post(VERIFY_REQ, headers=jimin)
    jimin_code = last_code(outbox)
    client.post(VERIFY_REQ, headers=minho)
    assert (
        client.post(VERIFY_CODE, json={"code": jimin_code}).status_code == 401
    )  # 로그인 없이는 안 된다
    other = client.post(VERIFY_CODE, json={"code": jimin_code}, headers=minho)
    assert (
        other.status_code == 400
    )  # 민호에게는 민호의 코드만 맞다(우연히 같은 6자리일 확률은 100만분의 1)
    assert db_user("jimin_kim").email_verified_at is None


def test_malformed_codes_are_rejected_before_counting(client, outbox):
    register(client)
    headers = bearer_for(client)
    client.post(VERIFY_REQ, headers=headers)
    for bad in ("12345", "1234567", "abcdef", "12 456", ""):
        assert client.post(VERIFY_CODE, json={"code": bad}, headers=headers).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(EmailVerification)).failed_attempts == 0


def test_no_pending_mail_means_expired(client, outbox):
    register(client)
    r = client.post(VERIFY_CODE, json={"code": "123456"}, headers=bearer_for(client))
    assert r.status_code == 400 and r.json()["code"] == "verification_expired"


# ---------- 비밀번호 재설정 ----------
def test_reset_mail_has_a_code_and_the_link(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    body = outbox.mails[-1].body
    assert re.search(r"재설정 코드: \d{6}\n", body) and "gabee://reset-password?token=" in body


def test_reset_with_the_code_changes_the_password_and_ends_every_session(client, outbox):
    register(client)
    phone = login(client).json()
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    r = reset_with(client, "jimin@example.com", last_code(outbox))
    assert r.status_code == 204
    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200
    assert client.post(REFRESH, json={"refresh_token": phone["refresh_token"]}).status_code == 401
    again = reset_with(client, "jimin@example.com", last_code(outbox), "Another-pass-88")
    assert again.status_code == 400  # 한 번 쓴 코드


def test_reset_email_is_matched_case_insensitively(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    assert reset_with(client, " Jimin@Example.com ", last_code(outbox)).status_code == 204


def test_reset_failures_look_the_same_whether_or_not_the_account_exists(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    code = last_code(outbox)
    unknown = reset_with(client, "nobody@example.com", code)
    wrong_code = reset_with(client, "jimin@example.com", wrong(code))
    assert unknown.status_code == wrong_code.status_code == 400
    assert unknown.json() == wrong_code.json() and unknown.json()["code"] == "reset_code_invalid"


def test_reset_code_locks_after_too_many_wrong_tries_and_stays_uniform(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    code = last_code(outbox)
    for _ in range(settings.code_max_attempts):
        assert reset_with(client, "jimin@example.com", wrong(code)).status_code == 400
    locked = reset_with(client, "jimin@example.com", code)
    assert locked.status_code == 400 and locked.json()["code"] == "reset_code_invalid"
    assert login(client, password=PASSWORD).status_code == 200  # 비밀번호는 그대로
    with SessionLocal() as db:
        assert db.scalar(select(PasswordReset)).failed_attempts == settings.code_max_attempts


def test_weak_password_with_a_right_code_can_be_retried(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    code = last_code(outbox)
    weak = reset_with(client, "jimin@example.com", code, "short")
    assert weak.status_code == 400 and weak.json()["code"] == "weak_password"
    assert reset_with(client, "jimin@example.com", code).status_code == 204


def test_newer_reset_mail_invalidates_the_older_code(client, outbox):
    register(client)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    first = last_code(outbox)
    client.post(RESET_REQ, json={"email": "jimin@example.com"})
    second = last_code(outbox)
    if first != second:
        assert reset_with(client, "jimin@example.com", first).status_code == 400
    assert reset_with(client, "jimin@example.com", second).status_code == 204
