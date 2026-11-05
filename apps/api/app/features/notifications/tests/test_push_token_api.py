"""푸시 토큰 등록·해제 API(/notifications/push-token) 시험."""

from sqlalchemy import select

from app.shared.db import SessionLocal
from app.shared.push_models import PushToken

URL = "/notifications/push-token"
TOKEN = "ExponentPushToken[abcdefghijklmnop]"


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _rows() -> list[PushToken]:
    with SessionLocal() as db:
        return list(db.scalars(select(PushToken)))


def _register(client, headers, token=TOKEN, **over):
    body = {"token": token, "platform": "android", "device_label": "시험 폰", **over}
    return client.put(URL, json=body, headers=headers)


def test_requires_login(client):
    assert client.put(URL, json={"token": TOKEN, "platform": "android"}).status_code == 401
    assert client.request("DELETE", URL, json={"token": TOKEN}).status_code == 401


def test_register_creates_row(client, family):
    a, _b, _group = family
    assert _register(client, a).status_code == 204
    [row] = _rows()
    assert (row.user_id, row.token, row.platform, row.device_label) == (
        _me(client, a),
        TOKEN,
        "android",
        "시험 폰",
    )


def test_reregister_same_user_updates_not_duplicates(client, family):
    a, _b, _group = family
    _register(client, a, device_label="처음")
    first = _rows()[0].last_seen_at
    assert _register(client, a, device_label="바꿈").status_code == 204
    [row] = _rows()
    assert row.device_label == "바꿈" and row.last_seen_at >= first


def test_token_moves_to_new_owner(client, family):
    a, b, _group = family
    _register(client, a)
    assert _register(client, b).status_code == 204
    [row] = _rows()  # 줄은 하나, 소유자만 바뀐다
    assert row.user_id == _me(client, b)


def test_two_devices_for_one_user(client, family):
    a, _b, _group = family
    _register(client, a)
    _register(client, a, token="ExpoPushToken[second-device-token]")
    assert len(_rows()) == 2


def test_bad_token_format_is_422(client, family):
    a, _b, _group = family
    for bad in (
        "abc",
        "",
        "ExponentPushToken[x",
        "Exponent[abc]",
        "ExponentPushToken[" + "x" * 300 + "]",
    ):
        assert _register(client, a, token=bad).status_code == 422, bad
    assert _register(client, a, platform="web").status_code == 422
    assert _rows() == []


def test_delete_own_token(client, family):
    a, _b, _group = family
    _register(client, a)
    assert client.request("DELETE", URL, json={"token": TOKEN}, headers=a).status_code == 204
    assert _rows() == []
    # 이미 없어도 204
    assert client.request("DELETE", URL, json={"token": TOKEN}, headers=a).status_code == 204


def test_cannot_delete_others_token(client, family):
    a, b, _group = family
    _register(client, a)
    assert client.request("DELETE", URL, json={"token": TOKEN}, headers=b).status_code == 204
    [row] = _rows()  # 남의 토큰은 그대로 남는다
    assert row.user_id == _me(client, a)
