"""앱 공지사항 보기: 로그인한 사람 누구나(가족이 없어도) 같은 목록을 최근순으로 본다."""

from datetime import UTC, datetime, timedelta

from app.features.notices.models import Notice
from app.shared.db import SessionLocal

PASSWORD = "Sunny-day-2026"


def _login(client, login_id="jimin_kim") -> dict:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post("/family-group/auth/login", json={"login_id": login_id, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_requires_login(client):
    assert client.get("/notices").status_code == 401


def test_empty_and_latest_first(client):
    headers = _login(client)
    assert client.get("/notices", headers=headers).json() == {"rows": []}
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add_all(
            [
                Notice(
                    category="info",
                    title="오래된 안내",
                    body="a",
                    created_at=now - timedelta(days=2),
                    updated_at=now,
                ),
                Notice(
                    category="update", title="새 업데이트", body="b", created_at=now, updated_at=now
                ),
            ]
        )
        db.commit()
    rows = client.get("/notices", headers=headers).json()["rows"]
    assert [(r["title"], r["category"]) for r in rows] == [
        ("새 업데이트", "update"),
        ("오래된 안내", "info"),
    ]
    assert set(rows[0]) == {"id", "category", "title", "body", "created_at", "updated_at"}
