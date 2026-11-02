"""아이디/비밀번호/이메일 회원가입(POST /family-group/auth/signup)."""

import pytest
from sqlalchemy import select

from app.features.family_group import credentials
from app.features.family_group.models import User
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.passwords import hash_password, needs_rehash, verify_password

URL = "/family-group/auth/signup"


def body(**over):
    data = {
        "login_id": "jimin_kim",
        "password": "Sunny-day-2026",
        "email": "jimin@example.com",
        "name": "김지민",
    }
    data.update(over)
    return data


def stored(login_id: str) -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.login_id == login_id))


# ---------- 성공 ----------
def test_signup_creates_a_credentialed_user_without_leaking_secrets(client):
    r = client.post(URL, json=body())
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert set(r.json()) == {"user"}  # 토큰은 발급하지 않는다(로그인 단계에서 발급)
    assert user["login_id"] == "jimin_kim" and user["email"] == "jimin@example.com"
    assert user["name"] == "김지민" and user["role"] == "child"
    assert user["email_verified"] is False and user["active_group_id"] is None
    assert "password" not in r.text and "token" not in r.text and "hash" not in r.text

    row = stored("jimin_kim")
    assert row.password_hash.startswith("$argon2id$") and "Sunny-day-2026" not in row.password_hash
    assert verify_password(row.password_hash, "Sunny-day-2026")
    assert row.email_verified_at is None and row.active_group_id is None


def test_ids_and_email_are_normalized(client):
    r = client.post(
        URL, json=body(login_id="  Jimin_Kim ", email=" JiMin@Example.COM ", name=" 김  지민 ")
    )
    assert r.status_code == 201
    user = r.json()["user"]
    assert (user["login_id"], user["email"], user["name"]) == (
        "jimin_kim",
        "jimin@example.com",
        "김 지민",
    )


def test_same_password_produces_different_salted_hashes(client):
    client.post(URL, json=body())
    client.post(URL, json=body(login_id="other_id", email="o@example.com"))
    assert stored("jimin_kim").password_hash != stored("other_id").password_hash


# ---------- 중복 ----------
def test_duplicate_login_id_is_rejected_case_insensitively(client):
    assert client.post(URL, json=body()).status_code == 201
    r = client.post(URL, json=body(login_id="JIMIN_KIM", email="other@example.com"))
    assert r.status_code == 409 and r.json()["code"] == "login_id_taken"
    assert set(r.json()) == {"code", "message"}


def test_duplicate_email_is_rejected_case_insensitively(client):
    assert client.post(URL, json=body()).status_code == 201
    r = client.post(URL, json=body(login_id="another_id", email="JIMIN@example.com"))
    assert r.status_code == 409 and r.json()["code"] == "email_taken"
    with SessionLocal() as db:
        assert len(list(db.scalars(select(User)))) == 1  # 실패한 가입은 계정을 남기지 않는다


def test_login_id_availability_check(client):
    ok = client.get("/family-group/auth/login-id-available", params={"login_id": " Jimin_Kim "})
    assert ok.json() == {"login_id": "jimin_kim", "available": True}
    client.post(URL, json=body())
    taken = client.get("/family-group/auth/login-id-available", params={"login_id": "JIMIN_KIM"})
    assert taken.json()["available"] is False
    bad = client.get("/family-group/auth/login-id-available", params={"login_id": "x"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_login_id"


def test_database_unique_constraint_is_the_last_line_of_defense(client, monkeypatch):
    """사전 확인을 통과한 뒤 다른 요청이 먼저 저장한 상황(동시 가입)을 흉내 낸다."""
    from app.features.family_group import repository

    assert client.post(URL, json=body()).status_code == 201
    real_exists = repository.login_id_exists
    calls = []

    def first_check_misses(
        db, value
    ):  # 첫 사전 확인만 "없음" 으로 답한다(그 사이 다른 요청이 저장한 상황)
        calls.append(value)
        return False if len(calls) == 1 else real_exists(db, value)

    monkeypatch.setattr(repository, "login_id_exists", first_check_misses)
    r = client.post(URL, json=body(email="diff@example.com"))
    # 사전 확인이 뚫려도 DB 제약이 막고, 서버 오류(500)가 아니라 정상적인 충돌 응답으로 돌려준다
    assert r.status_code == 409 and r.json()["code"] == "login_id_taken"
    with SessionLocal() as db:
        assert len(list(db.scalars(select(User)))) == 1  # 롤백되어 계정이 늘지 않았다


# ---------- 입력 검증 ----------
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("login_id", "abc", "invalid_login_id"),  # 너무 짧음
        ("login_id", "a" * 33, "invalid_login_id"),
        ("login_id", "1abcde", "invalid_login_id"),  # 숫자로 시작
        ("login_id", "ji min", "invalid_login_id"),
        ("login_id", "지민아이디", "invalid_login_id"),
        ("login_id", "jimin-kim", "invalid_login_id"),
        ("login_id", "admin", "invalid_login_id"),  # 예약어
        ("login_id", "ROOT", "invalid_login_id"),
        ("email", "nope", "invalid_email"),
        ("email", "a@b", "invalid_email"),  # 도메인에 점 없음
        ("email", "a b@example.com", "invalid_email"),
        ("email", "a@@example.com", "invalid_email"),
        ("email", "a..b@example.com", "invalid_email"),
        ("email", "a@example..com", "invalid_email"),
        # 이메일 칸이 비어 있으면(빈 문자열·공백) 이제 "이메일 없음"이라 가입된다 — tests/test_optional_email.py 참고
        ("name", "   ", "invalid_name"),
        ("name", "가" * 41, "invalid_name"),
        ("password", "Short1", "weak_password"),  # 8자 미만
        ("password", "onlyletters", "weak_password"),  # 숫자 없음
        ("password", "12345678901", "weak_password"),  # 문자 없음
        ("password", "x1" * 65, "weak_password"),  # 128자 초과
        ("password", "Jimin_Kim-2026", "weak_password"),  # 아이디 포함
        ("password", "JIMIN-pass-1", "weak_password"),  # 이메일 아이디(jimin) 포함
    ],
)
def test_invalid_input_is_rejected_with_a_specific_code(client, field, value, code):
    r = client.post(URL, json=body(**{field: value}))
    assert r.status_code == 400, r.text
    assert r.json()["code"] == code and set(r.json()) == {"code", "message"}
    assert stored("jimin_kim") is None  # 계정이 만들어지지 않았다


def test_missing_fields_and_wrong_types_are_422(client):
    assert client.post(URL, json={}).status_code == 422
    assert client.post(URL, json=body(password=12345678)).status_code == 422
    assert client.post(URL, json=body(role="admin")).status_code == 422
    assert client.post(URL, json=body(password="a1" * 200)).status_code == 422  # 크기 상한(256)


def test_password_is_kept_exactly_as_typed(client):
    pw = " Spaced pass 7 "  # 앞뒤 공백도 비밀번호의 일부
    assert client.post(URL, json=body(password=pw)).status_code == 201
    row = stored("jimin_kim")
    assert verify_password(row.password_hash, pw) and not verify_password(
        row.password_hash, pw.strip()
    )


def test_unicode_password_is_allowed(client):
    assert client.post(URL, json=body(password="비밀번호-가나다-12")).status_code == 201


# ---------- 레거시 인증 우회 방지 ----------
def test_new_account_cannot_use_the_legacy_token_header(client):
    client.post(URL, json=body())
    row = stored("jimin_kim")
    # 저장된 token 값은 아무에게도 알려주지 않지만, 혹시 알아내더라도 레거시 인증으로 들어올 수 없다
    r = client.get("/family-group/me", headers={"X-Gyeot-Token": row.token})
    assert r.status_code == 401 and r.json()["code"] == "token_invalid"
    for path in ("/family-chat/messages", "/schedule/events", "/billing/expenses"):
        assert client.get(path, headers={"X-Gyeot-Token": row.token}).status_code == 401


def test_legacy_token_is_unusable_and_unique_per_account(client):
    client.post(URL, json=body())
    client.post(URL, json=body(login_id="second_id", email="s@example.com"))
    a, b = stored("jimin_kim").token, stored("second_id").token
    assert a != b and a.startswith("nologin:") and len(a) <= 64


def test_anonymous_legacy_accounts_still_work_and_report_no_credentials(client):
    from tests.helpers import signup

    headers = signup(client, "익명")
    me = client.get("/family-group/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["login_id"] is None and me.json()["email"] is None
    assert me.json()["email_verified"] is False


# ---------- 단위 ----------
def test_password_hashing_module():
    h = hash_password("Pass-word-12")
    assert h.startswith("$argon2id$") and verify_password(h, "Pass-word-12")
    assert not verify_password(h, "pass-word-12") and not verify_password("garbage", "x")
    assert needs_rehash(h) is False


def test_credentials_helpers():
    assert credentials.normalize_login_id(" Abc_1 ") == "abc_1"
    assert credentials.normalize_email(" A.B+c@Sub.Example.com ") == "a.b+c@sub.example.com"
    with pytest.raises(ApiError) as exc:
        credentials.validate_password("password1", "someone", "other@example.com")
        credentials.validate_password("abc12345", "abc12345", "x@y.com")
    assert exc.value.code == "weak_password"


# ---------- 관계 직접 입력(역할=기타) ----------
def test_other_role_keeps_the_typed_relation(client):
    r = client.post(URL, json=body(role="other", role_detail="  이모   "))
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "other" and r.json()["user"]["role_detail"] == "이모"
    assert stored("jimin_kim").role_detail == "이모"


def test_relation_is_ignored_unless_the_role_is_other(client):
    r = client.post(URL, json=body(role="parent", role_detail="이모"))
    assert r.status_code == 201 and r.json()["user"]["role_detail"] is None
    assert (
        client.post(URL, json=body(login_id="a_user1", email="a@example.com", role="other")).json()[
            "user"
        ]["role_detail"]
        is None
    )  # 비워 두어도 가입된다


def test_too_long_relation_is_rejected(client):
    r = client.post(URL, json=body(role="other", role_detail="가" * 41))
    assert r.status_code == 400 and r.json()["code"] == "invalid_role_detail"
