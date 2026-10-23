"""이전 월 예산 용돈 -> 용돈 장부 데이터 이전 리비전(719215db61ba)을 SQLite 에서 확인한다."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text

from app.features.billing.models import Allowance, AllowanceEntry, AllowanceUse
from app.shared.db import Base

REVISION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "719215db61ba_billing_allowance_ledger_from_old_.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("allowance_ledger_revision", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    for model in (Allowance, AllowanceUse, AllowanceEntry):
        Base.metadata.tables[model.__tablename__].create(engine)
    with engine.begin() as conn:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            text(
                "INSERT INTO allowances (id, group_id, child_id, month, budget) VALUES "
                "('a1','g1','c1','2026-09',5000), ('a2','g1','c1','2026-10',8000), "
                "('a3','g1','c2','2026-10',3000), ('a0','g1','c2','2026-09',0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO allowance_uses (id, allowance_id, amount, memo, date, created_at) VALUES "
                f"('u1','a1',2000,'간식','2026-09-03','{now}'), "
                f"('u2','a2',8000,'','2026-10-01','{now}'), "
                f"('u3','a3',1000,'문구','2026-10-05','{now}'), "
                f"('u9','missing',500,'주인 없음','2026-10-05','{now}')"
            )
        )
    return engine


def _run(engine, fn_name):
    module = _load()
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(module, fn_name)()


def _entries(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                AllowanceEntry.id,
                AllowanceEntry.child_id,
                AllowanceEntry.kind,
                AllowanceEntry.amount,
                AllowanceEntry.memo,
                AllowanceEntry.date,
                AllowanceEntry.source,
                AllowanceEntry.created_by,
            ).order_by(AllowanceEntry.id)
        ).all()
    return {r.id: r for r in rows}


def test_old_budgets_and_uses_are_copied_into_the_ledger_without_touching_old_tables(engine):
    _run(engine, "upgrade")
    got = _entries(engine)
    assert set(got) == {
        "mca1",
        "mca2",
        "mca3",
        "muu1",
        "muu2",
        "muu3",
    }  # 예산 0원·주인 없는 사용은 제외
    credit = got["mca2"]
    assert (credit.kind, credit.amount, credit.date, credit.child_id) == (
        "credit",
        8000,
        "2026-10-01",
        "c1",
    )
    assert (credit.source, credit.created_by) == ("manual", None)
    use = got["muu1"]
    assert (use.kind, use.amount, use.memo, use.date, use.child_id) == (
        "use",
        2000,
        "간식",
        "2026-09-03",
        "c1",
    )
    # 이전 테이블은 그대로
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM allowances")).scalar() == 4
        assert conn.execute(text("SELECT COUNT(*) FROM allowance_uses")).scalar() == 4


def test_balances_never_go_negative_and_match_the_old_remaining_per_child(engine):
    _run(engine, "upgrade")
    totals: dict[str, int] = {}
    for e in sorted(_entries(engine).values(), key=lambda r: (r.date, r.id)):
        totals[e.child_id] = totals.get(e.child_id, 0) + (
            e.amount if e.kind == "credit" else -e.amount
        )
        assert totals[e.child_id] >= 0, e
    # c1: (5000-2000) + (8000-8000) = 3000, c2: 3000-1000 = 2000 (이전 방식의 남은 금액 합과 같다)
    assert totals == {"c1": 3000, "c2": 2000}


def test_running_it_again_does_not_duplicate_and_downgrade_deletes_nothing(engine):
    _run(engine, "upgrade")
    _run(engine, "upgrade")
    assert len(_entries(engine)) == 6
    _run(engine, "downgrade")
    assert len(_entries(engine)) == 6


def test_empty_old_tables_are_a_no_op():
    engine = create_engine("sqlite://")
    for model in (Allowance, AllowanceUse, AllowanceEntry):
        Base.metadata.tables[model.__tablename__].create(engine)
    _run(engine, "upgrade")
    assert _entries(engine) == {}
