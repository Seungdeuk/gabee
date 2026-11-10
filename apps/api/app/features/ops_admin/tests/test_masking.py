"""오류 메시지 가림: 개인정보·식별자가 저장 문자열에 남지 않는지 확인한다. 값은 모두 가짜다."""

import pytest

from app.features.ops_admin import masking
from app.features.ops_admin.masking import FAILED, MASK, MAX_MESSAGE_LENGTH, mask_message


@pytest.mark.parametrize(
    "secret",
    [
        "someone@example.com",
        "010-1234-5678",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl",
        "3f2b8c1e-9d4a-4c7b-8e21-5a6f0d1c2b3e",
        "777f3f5a4e00",
    ],
)
def test_identifiers_and_contacts_are_removed(secret):
    out = mask_message(f"failed for {secret} while saving")
    assert secret not in out
    assert MASK in out
    assert out.startswith("failed for") and out.endswith("while saving")


def test_bearer_and_key_value_secrets_keep_the_name_but_drop_the_value():
    out = mask_message("auth failed Bearer abcdef123456 password=hunter22 token: t0k3n-value")
    assert "abcdef123456" not in out and "hunter22" not in out and "t0k3n-value" not in out
    assert "password" in out and "token" in out


def test_url_query_and_fragment_are_dropped_but_path_stays():
    out = mask_message("GET https://api.example.test/items/list?email=a@b.co&page=2#top failed")
    assert out == "GET https://api.example.test/items/list failed"


def test_sql_statement_and_parameters_are_cut():
    out = mask_message(
        "(psycopg.errors.UndefinedColumn) column x does not exist "
        "[SQL: SELECT * FROM users WHERE email = %(e)s] [parameters: {'e': 'a@b.co'}]"
    )
    assert out == "(psycopg.errors.UndefinedColumn) column x does not exist"


def test_constraint_detail_values_are_removed():
    out = mask_message("duplicate key Key (login_id)=(some_login) already exists.")
    assert "some_login" not in out
    assert "Key (login_id)=" in out


def test_user_home_directory_name_is_removed():
    win = mask_message(r"cannot open C:\Users\hojenn24\gabee\app.py")
    assert "hojenn24" not in win
    assert "/home/alice/app.py" not in mask_message("cannot open /home/alice/app.py")


def test_plain_messages_are_left_alone():
    assert mask_message("division by zero") == "division by zero"
    assert mask_message("connection refused") == "connection refused"


def test_whitespace_collapses_and_length_is_limited():
    assert mask_message("a\n\n  b\tc") == "a b c"
    assert len(mask_message("x" * 5000)) == MAX_MESSAGE_LENGTH


@pytest.mark.parametrize("empty", [None, "", "   ", "\n"])
def test_empty_input_gives_empty_string(empty):
    assert mask_message(empty) == ""


def test_masking_failure_drops_the_message_instead_of_leaking_it(monkeypatch):
    def boom(_text):
        raise RuntimeError("detector broke")

    monkeypatch.setattr(masking, "detect", boom)
    out = mask_message("someone@example.com")
    assert out == FAILED and "example.com" not in out


def test_non_string_values_are_handled():
    assert mask_message(ValueError("bad value 777f3f5a4e00")) == f"bad value {MASK}"


def test_ip_addresses_are_removed():
    out = mask_message("connection from 203.0.113.7 to server at 10.0.0.5 failed")
    assert "203.0.113.7" not in out and "10.0.0.5" not in out
    assert out.count(MASK) == 2
