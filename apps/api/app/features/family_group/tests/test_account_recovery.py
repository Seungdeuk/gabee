"""아이디 찾기와 아이디+이메일 비밀번호 찾기(메일은 가짜 발송기로 가로챈다 — 실제 메일을 보내지 않는다)."""

import pytest

from app.features.family_group import service
from app.shared import mailer
from app.shared.config import settings
from tests.helpers import signup

from .test_email_flows import RESET_REQ, Outbox, db_user, login, register

RECOVER = "/family-group/auth/login-id/recover"
RESET_CODE = "/family-group/auth/password/reset/confirm-code"


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox().watch(monkeypatch)
    mailer.set_mailer(box)
    return box


def reset(client, login_id, email):
    return client.post(RESET_REQ, json={"login_id": login_id, "email": email})


def recover(client, email):
    return client.post(RECOVER, json={"email": email})


# ---------- 비밀번호 찾기: 아이디와 이메일이 둘 다 맞아야 보낸다 ----------
def test_reset_mail_goes_out_only_when_login_id_and_email_both_match(client, outbox):
    register(client, "jimin_kim", "jimin@example.com")
    register(client, "other_kim", "other@example.com")
    assert reset(client, "jimin_kim", "jimin@example.com").status_code == 204
    assert len(outbox.mails) == 1 and outbox.mails[0].to == "jimin@example.com"
    # 아이디만 맞거나(남의 이메일), 이메일만 맞거나(남의 아이디), 둘 다 없는 경우는 보내지 않고 "일치하지 않아요"
    for login_id, email in (
        ("jimin_kim", "other@example.com"),
        ("other_kim", "jimin@example.com"),
        ("ghost_x", "ghost@example.com"),
    ):
        r = reset(client, login_id, email)
        assert r.status_code == 400 and r.json()["code"] == "reset_mismatch", (login_id, email)
    assert len(outbox.mails) == 1


def test_mismatch_gives_one_message_and_never_says_which_part_is_wrong(client, outbox):
    """짝이 맞지 않으면 "아이디와 이메일이 일치하지 않아요" 하나다. 아이디가 없어서인지, 이메일이 틀려서인지, 이메일이 없는 계정인지
    구분되지 않아(응답 본문이 모두 같다) 아이디의 존재 여부나 다른 사람의 이메일을 알아낼 수 없다."""
    register(client, "jimin_kim", "jimin@example.com")
    assert signup(client, "익명")
    match = reset(client, "jimin_kim", "jimin@example.com")
    assert match.status_code == 204 and match.content == b""
    wrong_email = reset(client, "jimin_kim", "nobody@example.com")
    wrong_id = reset(client, "nobody_x", "jimin@example.com")
    no_account = reset(client, "nobody_x", "nobody@example.com")
    anonymous = reset(client, "anonymous", "anon@example.com")
    responses = [wrong_email, wrong_id, no_account, anonymous]
    assert all(r.status_code == 400 for r in responses)
    assert len({r.content for r in responses}) == 1  # 본문이 모두 같다
    assert wrong_email.json()["message"] == "아이디와 이메일이 일치하지 않아요"
    assert wrong_email.json()["code"] == "reset_mismatch"


def test_mismatch_attempts_count_toward_the_rate_limit(client, outbox, monkeypatch):
    """ "일치하지 않아요"를 알려 주는 대신, 짝을 계속 바꿔 대입하는 것은 이메일별·IP별 요청 제한이 막는다(불일치도 횟수에 센다)."""
    register(client)
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 2)
    assert [reset(client, "ghost_x", "jimin@example.com").status_code for _ in range(4)] == [
        400,
        400,
        429,
        429,
    ]
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 100)
    monkeypatch.setattr(settings, "reset_max_per_ip_per_hour", 3)
    service.mail_limiter.reset()
    guesses = [reset(client, "jimin_kim", f"guess{i}@example.com").status_code for i in range(5)]
    assert guesses == [400, 400, 400, 429, 429]
    assert outbox.mails == []


def test_reset_login_id_is_case_and_space_insensitive_in_the_request(client, outbox):
    register(client)
    assert reset(client, "  JIMIN_Kim ", "Jimin@Example.com").status_code == 204
    assert len(outbox.mails) == 1


def test_anonymous_accounts_never_get_a_reset_mail(client, outbox):
    assert signup(client, "익명")
    r = reset(client, "anonymous", "anon@example.com")
    assert r.status_code == 400 and r.json()["code"] == "reset_mismatch"
    assert outbox.mails == []


def test_reset_code_is_confirmed_with_the_login_id_not_the_email(client, outbox):
    register(client)
    reset(client, "jimin_kim", "jimin@example.com")
    import re

    code = re.search(r"재설정 코드: (\d{6})\n", outbox.mails[-1].body).group(1)
    body = {"code": code, "new_password": "Brand-new-pass-77"}
    # 옛 방식(이메일만 보내기)은 더 이상 받지 않는다
    assert client.post(RESET_CODE, json={"email": "jimin@example.com", **body}).status_code == 422
    # 없는 아이디는 틀린 코드와 같은 응답이다
    ghost = client.post(RESET_CODE, json={"login_id": "ghost_x", **body})
    assert ghost.status_code == 400 and ghost.json()["code"] == "reset_code_invalid"
    ok = client.post(RESET_CODE, json={"login_id": "jimin_kim", **body})
    assert ok.status_code == 204
    assert login(client, password="Brand-new-pass-77").status_code == 200


# ---------- 아이디 찾기 ----------
def test_recover_sends_the_login_id_to_the_registered_email_only(client, outbox):
    register(client, "jimin_kim", "jimin@example.com")
    register(client, "other_kim", "other@example.com")
    r = recover(client, "jimin@example.com")
    assert r.status_code == 204 and r.content == b""  # 아이디는 응답에 없다
    (mail,) = outbox.mails
    assert mail.to == "jimin@example.com" and "jimin_kim" in mail.body
    assert "jimin_kim" in mail.html and "other_kim" not in mail.body + mail.html
    assert "gabee://" not in mail.body + mail.html and "href" not in mail.html
    assert outbox.tokens == []  # 아이디 안내는 토큰·코드를 만들지 않는다


def test_recover_response_is_the_same_whether_or_not_the_email_is_registered(client, outbox):
    register(client)
    known = recover(client, "jimin@example.com")
    unknown = recover(client, "nobody@example.com")
    assert known.status_code == unknown.status_code == 204
    assert known.content == unknown.content == b""
    assert len(outbox.mails) == 1  # 없는 주소로는 메일을 보내지 않는다


def test_recover_works_for_an_unverified_email_and_is_case_insensitive(client, outbox):
    register(client)
    assert db_user().email_verified_at is None
    assert recover(client, " Jimin@Example.com ").status_code == 204
    assert len(outbox.mails) == 1 and "jimin_kim" in outbox.mails[0].body


def test_recover_ignores_anonymous_accounts(client, outbox):
    assert signup(client, "익명")
    assert recover(client, "anon@example.com").status_code == 204
    assert outbox.mails == []


def test_recover_is_rate_limited_the_same_for_known_and_unknown_emails(client, outbox, monkeypatch):
    register(client)
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 2)
    assert [recover(client, "jimin@example.com").status_code for _ in range(4)] == [
        204,
        204,
        429,
        429,
    ]
    assert [recover(client, "ghost@example.com").status_code for _ in range(4)] == [
        204,
        204,
        429,
        429,
    ]
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 100)
    monkeypatch.setattr(settings, "reset_max_per_ip_per_hour", 3)
    service.mail_limiter.reset()
    mixed = [recover(client, f"user{i}@example.com").status_code for i in range(5)]
    assert mixed == [204, 204, 204, 429, 429]


def test_recover_and_reset_limits_are_counted_separately(client, outbox, monkeypatch):
    register(client)
    monkeypatch.setattr(settings, "reset_max_per_email_per_hour", 1)
    assert recover(client, "jimin@example.com").status_code == 204
    assert recover(client, "jimin@example.com").status_code == 429
    assert reset(client, "jimin_kim", "jimin@example.com").status_code == 204  # 별도 한도


def test_recover_without_mail_settings_is_503_regardless_of_the_account(client):
    register(client)
    mailer.set_mailer(None)
    for email in ("jimin@example.com", "nobody@example.com"):
        r = recover(client, email)
        assert r.status_code == 503 and r.json()["code"] == "mail_not_configured"


def test_recover_rejects_a_malformed_email_and_a_missing_body(client, outbox):
    assert recover(client, "not-an-email").status_code == 400
    assert client.post(RECOVER, json={}).status_code == 422
    assert outbox.mails == []


def test_a_failed_send_is_logged_but_not_shown_to_the_requester(client, caplog):
    register(client)
    mailer.set_mailer(Outbox(fail=True))
    with caplog.at_level("ERROR"):
        r = recover(client, "jimin@example.com")
    assert r.status_code == 204
    assert "mail_delivery_failed kind=login_id_recover" in caplog.text
    assert "jimin@example.com" not in caplog.text and "jimin_kim" not in caplog.text
