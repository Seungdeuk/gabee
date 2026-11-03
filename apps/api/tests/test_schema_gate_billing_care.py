"""가계·돌봄의 최신 리비전이 DB 에 아직 적용되지 않았을 때: 서버는 살아 있고 그 기능만 503, 적용되면 재시작 없이 열린다.

SQLite 로 스키마를 일부러 어긋나게 만든다(실제 PostgreSQL 흐름은 test_schema_gate_pg_e2e.py).
"""

import pytest
from sqlalchemy import text

from app.shared.config import settings
from app.shared.db import engine
from app.shared.schema import monitor


@pytest.fixture(autouse=True)
def instant_recheck(monkeypatch):
    monkeypatch.setattr(settings, "schema_recheck_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_recheck_not_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_force_min_interval_seconds", 0)
    monitor.reset()
    yield
    monitor.reset()


def _drop(table: str, column: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def _add(table: str, column: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def test_billing_without_discount_column_is_503_but_care_and_others_keep_working(client, family):
    a, _, _ = family
    _drop("subscription_items", "discount_amount")  # f972aab92bdb 적용 전

    for path in ("/billing/subscriptions", "/billing/subscriptions/catalog", "/billing/expenses"):
        r = client.get(path, headers=a)
        assert r.status_code == 503 and r.json()["code"] == "schema_not_ready", path
        assert r.headers["retry-after"] == "5"
    assert client.get("/care/location/consent", headers=a).status_code == 200
    assert client.get("/family-group/me", headers=a).status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    report = client.get("/health/db").json()
    assert report["features"]["billing"] == {"ready": False, "reason": "missing_schema"}
    assert report["features"]["care"]["ready"] is True

    _add("subscription_items", "discount_amount", "INTEGER")  # 마이그레이션 적용 완료
    assert client.get("/billing/subscriptions", headers=a).status_code == 200  # 재시작 없이 열림
    assert client.get("/health/db").json()["features"]["billing"]["ready"] is True


def test_care_without_its_columns_is_503_but_billing_keeps_working(client, family):
    a, _, _ = family
    _drop("care_entries", "skipped")  # 건너뛰기 컬럼이 아직 없는 DB

    r = client.get("/care/location/consent", headers=a)
    assert r.status_code == 503 and r.json()["code"] == "schema_not_ready"
    assert client.get("/billing/subscriptions", headers=a).status_code == 200
    assert client.get("/billing/expenses", headers=a).status_code == 200
    assert client.get("/health/db").json()["features"]["care"] == {
        "ready": False,
        "reason": "missing_schema",
    }
