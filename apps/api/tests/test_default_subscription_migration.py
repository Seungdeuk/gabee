"""기본 구독 5개를 아무도 손대지 않은 그룹에서만 감추는 리비전(9eb94b284ac7)을 SQLite 에서 확인한다."""

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.features.billing.models import SubscriptionItem
from app.shared.db import Base

REVISION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "9eb94b284ac7_billing_hide_untouched_default_.py"
)


def _upgrade(engine):
    spec = importlib.util.spec_from_file_location("hide_defaults_revision", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def _insert(conn, id, kind, name, **extra):
    row = {
        "id": id,
        "group_id": "g1",
        "kind": kind,
        "name": name,
        "status": "check",
        "sort_order": 0,
        "carrier": None,
        "monthly_fee": None,
        "discount_amount": None,
        "billing_day": None,
        "payer_id": None,
        "split_among": json.dumps([]),
        "deleted_at": None,
        "updated_at": "2026-10-01 00:00:00",
        **extra,
    }
    if isinstance(row["split_among"], list):
        row["split_among"] = json.dumps(row["split_among"])
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    conn.execute(text(f"INSERT INTO subscription_items ({cols}) VALUES ({marks})"), row)


def _deleted(engine) -> dict[str, bool]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, deleted_at FROM subscription_items")).all()
    return {r.id: r.deleted_at is not None for r in rows}


def test_only_untouched_defaults_are_hidden_and_nothing_is_deleted():
    engine = create_engine("sqlite://")
    Base.metadata.tables[SubscriptionItem.__tablename__].create(engine)
    with engine.begin() as conn:
        _insert(conn, "d1", "ott", "넷플릭스")  # 기본 그대로 -> 감춘다
        _insert(conn, "d2", "telecom", "가족 결합 할인")
        _insert(conn, "t_status", "ott", "유튜브 프리미엄", status="active")  # 상태를 바꿈
        _insert(conn, "t_fee", "ott", "디즈니+", monthly_fee=9900)  # 금액을 넣음
        _insert(conn, "t_day", "telecom", "요금제 결합 할인", billing_day=5)
        _insert(conn, "t_payer", "ott", "넷플릭스", payer_id="u1")  # 사용자가 직접 만든 같은 이름
        _insert(conn, "t_split", "ott", "넷플릭스", split_among=["u1", "u2"])
        _insert(conn, "t_carrier", "telecom", "가족 결합 할인", carrier="skt")
        _insert(conn, "own", "ott", "왓챠")  # 기본 이름이 아님
        _insert(conn, "already", "ott", "넷플릭스", deleted_at="2026-10-01 00:00:00")
    _upgrade(engine)
    got = _deleted(engine)
    assert got == {
        "d1": True,
        "d2": True,
        "t_status": False,
        "t_fee": False,
        "t_day": False,
        "t_payer": False,
        "t_split": False,
        "t_carrier": False,
        "own": False,
        "already": True,  # 이미 감춘 항목은 그대로
    }
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT COUNT(*) FROM subscription_items")).scalar() == 10
        )  # 삭제 없음


def test_running_twice_and_empty_table_are_safe():
    engine = create_engine("sqlite://")
    Base.metadata.tables[SubscriptionItem.__tablename__].create(engine)
    _upgrade(engine)  # 빈 테이블
    with engine.begin() as conn:
        _insert(conn, "d1", "ott", "넷플릭스")
    _upgrade(engine)
    _upgrade(engine)
    assert _deleted(engine) == {"d1": True}
