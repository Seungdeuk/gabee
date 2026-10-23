"""이메일은 가입 때 선택이고, 이메일이 없거나 인증하지 않아도 가족 그룹에 참여할 수 있다."""

import pytest
from sqlalchemy import select

from app.features.family_group.models import User
from app.shared import mailer
from app.shared.config import settings
from app.shared.db import SessionLocal

from .test_join_approval import P, create_group, join

PASSWORD = "Sunny-day-2026"
SIGNUP = f"{P}/auth/signup"


def signup_body(login_id, **over):
    data = {"login_id": login_id, "password": PASSWORD, "name": login_id}
    data.update(over)
    return data


def make(client, login_id, **over):
    r = client.post(SIGNUP, json=signup_body(login_id, **over))
    assert r.status_code == 201, r.text
    token = client.post(
        f"{P}/auth/login", json={"login_id": login_id, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, r.json()["user"]


@pytest.fixture
def mail_on():
    class Outbox:
        def send(self, mail):
            pass

    mailer.set_mailer(Outbox())  # 메일이 설정된 환경


@pytest.mark.parametrize("email", [None, "", "   "])
def test_signup_works_without_an_email(client, email):
    body = signup_body("no_email_a")
    if email is not None:
        body["email"] = email
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert (
        user["email"] is None
        and user["email_verified"] is False
        and user["login_id"] == "no_email_a"
    )
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.login_id == "no_email_a")).email is None


def test_many_accounts_can_have_no_email_but_a_given_email_is_still_unique_and_checked(client):
    make(client, "no_email_a")
    make(client, "no_email_b")  # 이메일이 없는 계정끼리는 중복이 아니다
    make(client, "with_email", email="Hello@Example.com")
    dup = client.post(SIGNUP, json=signup_body("other_one", email="hello@example.com"))
    assert dup.status_code == 409 and dup.json()["code"] == "email_taken"
    bad = client.post(SIGNUP, json=signup_body("other_two", email="not-an-email"))
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_email"
    assert (
        client.get(f"{P}/auth/login-id-available", params={"login_id": "no_email_a"}).json()[
            "available"
        ]
        is False
    )


def test_password_rules_still_apply_without_an_email(client):
    weak = client.post(SIGNUP, json=signup_body("no_email_a", password="short"))
    assert weak.status_code == 400 and weak.json()["code"] == "weak_password"
    contains_id = client.post(SIGNUP, json=signup_body("no_email_a", password="no_email_a-2026"))
    assert contains_id.status_code == 400 and contains_id.json()["code"] == "weak_password"


def test_member_without_an_email_can_create_a_family_and_others_can_join(client, mail_on):
    owner, _ = make(client, "mom_kim")
    group = create_group(client, owner)
    guest, guest_user = make(client, "jimin_lee")
    pending = join(client, guest, group["invite_code"])
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    approved = client.post(
        f"{P}/groups/join-requests/{pending.json()['id']}/approve", headers=owner
    )
    assert approved.status_code == 200
    assert guest_user["id"] in [m["id"] for m in approved.json()["members"]]


def test_unverified_email_does_not_block_a_family_by_default(client, mail_on):
    owner, _ = make(client, "mom_kim", email="mom@example.com")  # 이메일은 있지만 인증하지 않았다
    group = create_group(client, owner)  # 메일이 설정돼 있어도 만들 수 있다
    guest, _ = make(client, "jimin_lee", email="jimin@example.com")
    assert join(client, guest, group["invite_code"]).json()["status"] == "pending"


def test_opting_in_blocks_only_accounts_that_have_an_unverified_email(client, mail_on, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", True)
    unverified, _ = make(client, "mom_kim", email="mom@example.com")
    blocked = client.post(f"{P}/groups", json={"name": "가족"}, headers=unverified)
    assert blocked.status_code == 403 and blocked.json()["code"] == "email_not_verified"
    no_email, _ = make(client, "dad_kim")  # 이메일이 없으면 인증할 수단이 없어 막지 않는다
    assert client.post(f"{P}/groups", json={"name": "가족"}, headers=no_email).status_code == 201


def test_features_that_need_an_email_say_so_instead_of_failing_oddly(client, mail_on):
    headers, _ = make(client, "no_email_a")
    verify = client.post(f"{P}/auth/email/verify/request", headers=headers)
    assert verify.status_code == 400 and verify.json()["code"] == "no_email"
    # 비밀번호 재설정은 가입한 이메일로만 할 수 있어서 이메일이 없는 계정에는 아무것도 보내지 않는다(응답은 다른 주소와 같다)
    assert (
        client.post(
            f"{P}/auth/password/reset/request", json={"email": "nobody@example.com"}
        ).status_code
        == 204
    )
