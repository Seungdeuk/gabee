"""유입 경로 저장: 본인 것만, 처음 값만, 가입 30일 안인 회원만 저장한다."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import signup

URL = "/acquisition/install-source"
YOUTUBE = {"source": "youtube", "medium": "video", "campaign": "launch"}


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _row(user_id: str):
    from app.features.acquisition.models import InstallSource
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        row = db.get(InstallSource, user_id)
        return None if row is None else (row.source, row.medium, row.campaign)


@pytest.fixture(autouse=True)
def _clean(client):
    from app.features.acquisition.models import InstallSource
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        db.query(InstallSource).delete()
        db.commit()


def test_requires_login(client):
    assert client.post(URL, json=YOUTUBE).status_code == 401


def test_saves_first_source(client):
    h = signup(client, "민수")
    r = client.post(URL, json=YOUTUBE, headers=h)
    assert r.status_code == 204, r.text
    assert _row(_me(client, h)) == ("youtube", "video", "launch")


def test_keeps_first_value(client):
    h = signup(client, "민수")
    client.post(URL, json=YOUTUBE, headers=h)
    r = client.post(URL, json={"source": "instagram", "medium": "sns"}, headers=h)
    assert r.status_code == 204  # 두 번째도 같은 답(앱은 구분하지 않는다)
    assert _row(_me(client, h)) == ("youtube", "video", "launch")


def test_source_only(client):
    h = signup(client, "민수")
    assert client.post(URL, json={"source": "google-play"}, headers=h).status_code == 204
    assert _row(_me(client, h)) == ("google-play", None, None)


def test_user_without_family_can_send(client):
    h = signup(client, "지민")  # 가족 없음
    assert client.post(URL, json={"source": "news"}, headers=h).status_code == 204


def test_family_member_can_send(client, family):
    a, _, _ = family
    assert client.post(URL, json={"source": "blog"}, headers=a).status_code == 204
    assert _row(_me(client, a))[0] == "blog"


def test_old_member_is_not_saved(client):
    from app.features.family_group.models import User
    from app.shared.db import SessionLocal

    h = signup(client, "민수")
    uid = _me(client, h)
    with SessionLocal() as db:
        db.get(User, uid).created_at = datetime.now(UTC) - timedelta(days=31)
        db.commit()
    assert client.post(URL, json=YOUTUBE, headers=h).status_code == 204
    assert _row(uid) is None


@pytest.mark.parametrize(
    "body",
    [
        {},  # source 없음
        {"source": ""},
        {"source": "YouTube"},  # 대문자
        {"source": "you tube"},  # 공백
        {"source": "유튜브"},  # 한글
        {"source": "a" * 41},  # 너무 김
        {"source": "youtube", "medium": "video&x=1"},  # 꼬리표 원문 조각
        {"source": "youtube", "campaign": "<script>"},
    ],
)
def test_invalid_values_are_rejected(client, body):
    h = signup(client, "민수")
    assert client.post(URL, json=body, headers=h).status_code == 422, body
    assert _row(_me(client, h)) is None


def test_saves_only_for_caller(client, family):
    a, b, _ = family
    client.post(URL, json=YOUTUBE, headers=a)
    assert _row(_me(client, b)) is None
