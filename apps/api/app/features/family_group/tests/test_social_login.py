"""Google·Kakao 로그인과 계정 연동(PR 4-D). 제공자 검증은 가짜로 바꿔 끼운다 — 실제 Google·Kakao 서버에 접속하지 않는다."""

import time

import pytest
from sqlalchemy import select

from app.features.family_group import social_providers as providers
from app.features.family_group.models import RefreshToken, SocialAccount, User
from app.shared import mailer
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

from .test_join_approval import P, account, join

pytestmark = pytest.mark.usefixtures("approval_required")  # 승인 대기 흐름을 본다

TOKEN = "x" * 20


@pytest.fixture(autouse=True)
def _reset_verifiers():
    yield
    providers._overrides.clear()


def fake(provider, uid, email=None, name="지민"):
    providers.set_verifier(provider, lambda token: providers.Identity(provider, uid, email, name))


def social(client, provider="google", **body):
    return client.post(f"{P}/auth/social/{provider}", json={"provider_token": TOKEN, **body})


def bearer(res):
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def users():
    with SessionLocal() as db:
        return list(db.scalars(select(User)))


def accounts():
    with SessionLocal() as db:
        return list(db.scalars(select(SocialAccount)))


# ---------- 로그인·가입 ----------
def test_first_social_login_creates_a_password_less_verified_account(client):
    fake("google", "g-1", "jimin@gmail.com")
    r = social(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "jimin@gmail.com" and body["user"]["email_verified"] is True
    assert body["user"]["login_id"] is None and body["user"]["name"] == "지민"
    assert (
        client.get(f"{P}/auth/me", headers=bearer(r)).json()["id"] == body["user"]["id"]
    )  # 발급된 토큰이 쓸 수 있다
    (user,) = users()
    assert user.password_hash is None and user.token.startswith("nologin:")
    (acct,) = accounts()
    assert (acct.provider, acct.provider_uid, acct.user_id) == ("google", "g-1", user.id)


def test_second_login_is_the_same_user_with_fresh_tokens(client):
    fake("google", "g-1", "jimin@gmail.com")
    first, second = social(client).json(), social(client).json()
    assert first["user"]["id"] == second["user"]["id"] and len(users()) == 1
    assert first["refresh_token"] != second["refresh_token"]
    with SessionLocal() as db:
        assert db.query(RefreshToken).count() == 2


def test_account_without_an_email_still_signs_up(client):
    fake("kakao", "k-1", None, "카카오")
    fake_two = providers.Identity("kakao", "k-2", None, "두번째")
    r1 = social(client, "kakao")
    providers.set_verifier("kakao", lambda token: fake_two)
    r2 = social(client, "kakao")
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["user"]["id"] != r2.json()["user"]["id"]
    assert all(u.email is None for u in users())  # 이메일이 없어도 unique 에 걸리지 않는다
    assert r1.json()["user"]["email_verified"] is False


def test_same_email_as_an_existing_account_is_never_merged(client):
    existing, existing_id = account(client, "jimin_kim", "지민")
    fake("google", "g-9", "jimin_kim@example.com")  # account() 가 만드는 이메일과 같다
    r = social(client)
    assert r.status_code == 200 and r.json() == {
        "candidate_account": True,
        "masked_email": "j***@example.com",
    }
    assert "access_token" not in r.text and "jimin_kim@example.com" not in r.text
    assert len(users()) == 1 and accounts() == []  # 새 계정도 연동도 만들지 않는다


def test_new_account_uses_the_requested_role_and_a_fallback_name(client):
    providers.set_verifier("google", lambda token: providers.Identity("google", "g-3", None, None))
    r = social(client, role="parent")
    assert r.json()["user"]["role"] == "parent" and r.json()["user"]["name"] == "가족"


# ---------- 설정·검증 실패 ----------
def test_unconfigured_provider_is_503_and_invalid_tokens_are_401(client):
    r = social(client, "google")  # GOOGLE_CLIENT_IDS 가 비어 있다
    assert r.status_code == 503 and r.json()["code"] == "social_not_configured"
    assert social(client, "kakao").json()["code"] == "social_not_configured"

    def reject(token):
        raise providers.ProviderRejected

    providers.set_verifier("google", reject)
    bad = social(client)
    assert (
        bad.status_code == 401
        and bad.json()["code"] == "social_token_invalid"
        and TOKEN not in bad.text
    )

    def down(token):
        raise providers.ProviderUnavailable

    providers.set_verifier("google", down)
    assert social(client).json()["code"] == "social_unavailable"
    assert users() == []


def test_repeated_rejections_are_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 3)

    def reject(token):
        raise providers.ProviderRejected

    providers.set_verifier("google", reject)
    for _ in range(3):
        assert social(client).status_code == 401
    blocked = social(client)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_unknown_provider_and_short_tokens_are_422(client):
    assert (
        client.post(f"{P}/auth/social/facebook", json={"provider_token": TOKEN}).status_code == 422
    )
    assert (
        client.post(f"{P}/auth/social/google", json={"provider_token": "short"}).status_code == 422
    )


# ---------- 연동 ----------
def test_link_requires_the_password_and_then_social_login_uses_the_same_account(client):
    headers, user_id = account(client, "jimin_kim", "지민")
    fake("google", "g-1", "other@gmail.com")
    link = f"{P}/auth/social/google/link"
    assert (
        client.post(link, json={"provider_token": TOKEN}, headers=headers).json()["code"]
        == "password_required"
    )
    wrong = client.post(
        link, json={"provider_token": TOKEN, "password": "Wrong-pass-1"}, headers=headers
    )
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_credentials"
    ok = client.post(
        link, json={"provider_token": TOKEN, "password": "Sunny-day-2026"}, headers=headers
    )
    assert ok.status_code == 204
    again = client.post(
        link, json={"provider_token": TOKEN, "password": "Sunny-day-2026"}, headers=headers
    )
    assert again.status_code == 204 and len(accounts()) == 1  # 같은 계정 재연동은 같은 결과
    listed = client.get(f"{P}/auth/social", headers=headers).json()
    assert [a["provider"] for a in listed] == ["google"]
    login = social(client)  # 이제 소셜 로그인이 같은 계정으로 들어온다
    assert login.json()["user"]["id"] == user_id and len(users()) == 1


def test_candidate_flow_ends_with_a_safe_link(client):
    headers, user_id = account(client, "jimin_kim", "지민")
    fake("google", "g-2", "jimin_kim@example.com")
    assert social(client).json()["candidate_account"] is True
    client.post(
        f"{P}/auth/social/google/link",
        json={"provider_token": TOKEN, "password": "Sunny-day-2026"},
        headers=headers,
    )
    assert social(client).json()["user"]["id"] == user_id


def test_a_social_account_cannot_be_linked_to_two_users_or_twice_per_provider(client):
    a, _ = account(client, "mom_kim", "엄마")
    b, _ = account(client, "dad_kim", "아빠")
    fake("google", "g-1")
    body = {"provider_token": TOKEN, "password": "Sunny-day-2026"}
    assert client.post(f"{P}/auth/social/google/link", json=body, headers=a).status_code == 204
    taken = client.post(f"{P}/auth/social/google/link", json=body, headers=b)
    assert taken.status_code == 409 and taken.json()["code"] == "social_already_linked"
    fake("google", "g-2")  # 같은 사람이 다른 Google 계정을 또 연결
    second = client.post(f"{P}/auth/social/google/link", json=body, headers=a)
    assert second.status_code == 409 and second.json()["code"] == "social_provider_already_linked"
    assert len(accounts()) == 1


def test_link_and_list_need_a_real_login(client):
    fake("google", "g-1")
    assert (
        client.post(f"{P}/auth/social/google/link", json={"provider_token": TOKEN}).status_code
        == 401
    )
    assert client.get(f"{P}/auth/social").status_code == 401
    anonymous = signup(client, "손님")
    assert (
        client.post(
            f"{P}/auth/social/google/link", json={"provider_token": TOKEN}, headers=anonymous
        ).status_code
        == 401
    )


# ---------- 해제: 마지막 로그인 수단 보호 ----------
def test_unlink_keeps_at_least_one_way_to_log_in(client):
    headers, _ = account(client, "jimin_kim", "지민")  # 비밀번호가 있다
    fake("google", "g-1")
    client.post(
        f"{P}/auth/social/google/link",
        json={"provider_token": TOKEN, "password": "Sunny-day-2026"},
        headers=headers,
    )
    assert (
        client.delete(f"{P}/auth/social/google", headers=headers).status_code == 204
    )  # 비밀번호가 남아 있어 해제 가능
    assert accounts() == []
    assert client.delete(f"{P}/auth/social/google", headers=headers).status_code == 404

    fake("google", "g-7", "solo@gmail.com")
    solo = social(client)  # 소셜 전용 계정
    denied = client.delete(f"{P}/auth/social/google", headers=bearer(solo))
    assert denied.status_code == 403 and denied.json()["code"] == "last_login_method"
    fake("kakao", "k-7")
    assert (
        client.post(
            f"{P}/auth/social/kakao/link", json={"provider_token": TOKEN}, headers=bearer(solo)
        ).status_code
        == 204
    )
    assert (
        client.delete(f"{P}/auth/social/google", headers=bearer(solo)).status_code == 204
    )  # 하나 남는다
    last = client.delete(f"{P}/auth/social/kakao", headers=bearer(solo))
    assert last.status_code == 403 and last.json()["code"] == "last_login_method"
    assert len(accounts()) == 1


def test_unlinking_both_accounts_one_after_another_keeps_the_last_one(client):
    # 동시에 해제하는 경우는 PostgreSQL 의 행 잠금(FOR UPDATE)에 기대는 동작이라 SQLite 로는 시험할 수 없다 — tests/test_social_pg_e2e.py 참고
    fake("google", "g-1", "solo@gmail.com")
    headers = bearer(social(client))
    fake("kakao", "k-1")
    client.post(f"{P}/auth/social/kakao/link", json={"provider_token": TOKEN}, headers=headers)
    first = client.delete(f"{P}/auth/social/google", headers=headers)
    second = client.delete(f"{P}/auth/social/kakao", headers=headers)
    assert (first.status_code, second.status_code) == (204, 403)
    assert [a.provider for a in accounts()] == ["kakao"]


# ---------- 가족 기능과의 연결 ----------
def test_social_member_can_create_a_family_and_gets_the_new_invite_policy(client):
    mailer.set_mailer(
        type("M", (), {"send": lambda self, mail: None})()
    )  # 메일이 설정된 환경(이메일 인증 정책 적용)
    fake("google", "g-1", "jimin@gmail.com")
    r = social(client)
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=bearer(r))
    assert group.status_code == 201, group.text  # 소셜 계정은 이메일 인증이 끝난 것으로 본다
    assert len(group.json()["invite_code"]) == 10 and group.json()["my_role"] == "owner"


def test_social_member_joining_needs_approval_even_for_anonymous_groups(client):
    anon = signup(client, "지민")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=anon).json()
    fake("kakao", "k-1")
    r = social(client, "kakao")
    pending = join(client, bearer(r), group["invite_code"])
    assert (
        pending.status_code == 200 and pending.json()["status"] == "pending"
    )  # 정식 회원이라 즉시 참여가 아니다


# ---------- 제공자 응답 해석(네트워크 없이) ----------
def test_google_token_checks_audience_issuer_expiry_and_email_verification(monkeypatch):
    monkeypatch.setattr(settings, "google_client_ids", "web-id, ios-id")
    good = {
        "aud": "ios-id",
        "iss": "https://accounts.google.com",
        "sub": "123",
        "exp": str(int(time.time()) + 600),
        "email": "a@b.com",
        "email_verified": "true",
        "name": "지민",
    }

    def serve(claims):
        monkeypatch.setattr(providers, "_fetch_json", lambda url, headers=None: claims)

    serve(good)
    ident = providers.verify("google", TOKEN)
    assert (ident.uid, ident.email, ident.name) == ("123", "a@b.com", "지민")
    serve({**good, "email_verified": "false"})
    assert providers.verify("google", TOKEN).email is None  # 검증 안 된 이메일은 쓰지 않는다
    for bad in (
        {"aud": "other"},
        {"iss": "https://evil.example"},
        {"exp": "1"},
        {"sub": ""},
        {"exp": "x"},
    ):
        serve({**good, **bad})
        with pytest.raises(providers.ProviderRejected):
            providers.verify("google", TOKEN)


def test_kakao_token_must_belong_to_our_app(monkeypatch):
    monkeypatch.setattr(settings, "kakao_app_id", "1234")
    answers = {
        "access_token_info": {"id": 1, "app_id": 1234},
        "user/me": {
            "id": 777,
            "kakao_account": {
                "email": "k@k.com",
                "is_email_valid": True,
                "is_email_verified": True,
                "profile": {"nickname": "닉네임"},
            },
        },
    }
    monkeypatch.setattr(
        providers,
        "_fetch_json",
        lambda url, headers=None: next(v for k, v in answers.items() if k in url),
    )
    ident = providers.verify("kakao", TOKEN)
    assert (ident.uid, ident.email, ident.name) == ("777", "k@k.com", "닉네임")
    answers["user/me"]["kakao_account"]["is_email_verified"] = False
    assert providers.verify("kakao", TOKEN).email is None
    answers["access_token_info"]["app_id"] = 9999  # 다른 앱에서 발급된 토큰
    with pytest.raises(providers.ProviderRejected):
        providers.verify("kakao", TOKEN)


def test_provider_network_errors_never_leak_tokens(monkeypatch):
    monkeypatch.setattr(settings, "kakao_app_id", "1234")

    def boom(url, headers=None):
        raise providers.ProviderUnavailable

    monkeypatch.setattr(providers, "_fetch_json", boom)
    with pytest.raises(providers.ProviderUnavailable) as info:
        providers.verify("kakao", TOKEN)
    assert TOKEN not in repr(info.value)
