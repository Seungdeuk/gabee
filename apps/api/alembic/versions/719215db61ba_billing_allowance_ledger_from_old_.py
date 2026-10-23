"""billing allowance ledger from old budgets

Revision ID: 719215db61ba
Revises: 6417c8cf2722
Create Date: 2026-10-23 18:00:00.000000

이전 "월 예산" 용돈 데이터를 용돈 장부로 옮긴다(복사만 하고 이전 테이블은 그대로 둔다 — 데이터 삭제 없음).
- 월 예산(allowances) 한 줄 -> 그 달 1일자 입금 한 줄(금액 = 예산, 메모 "월 용돈 (이전 방식)")
- 사용 기록(allowance_uses) 한 줄 -> 사용 한 줄(날짜·금액·메모 그대로)
옮긴 줄의 id 는 이전 id 에서 만들어(mc<예산 id> / mu<사용 id>) 같은 리비전을 다시 적용해도 중복되지 않는다.
이전 방식은 월 예산보다 많이 쓸 수 없었고 사용 날짜는 그 달 안이라, 옮긴 뒤에도 잔액이 음수가 되지 않는다.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "719215db61ba"
down_revision: str | Sequence[str] | None = "6417c8cf2722"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_allowances = sa.table(
    "allowances",
    sa.column("id", sa.String),
    sa.column("group_id", sa.String),
    sa.column("child_id", sa.String),
    sa.column("month", sa.String),
    sa.column("budget", sa.Integer),
)
_uses = sa.table(
    "allowance_uses",
    sa.column("id", sa.String),
    sa.column("allowance_id", sa.String),
    sa.column("amount", sa.Integer),
    sa.column("memo", sa.String),
    sa.column("date", sa.String),
)
_entries = sa.table(
    "allowance_entries",
    sa.column("id", sa.String),
    sa.column("group_id", sa.String),
    sa.column("child_id", sa.String),
    sa.column("kind", sa.String),
    sa.column("amount", sa.Integer),
    sa.column("memo", sa.String),
    sa.column("date", sa.String),
    sa.column("source", sa.String),
    sa.column("plan_due_date", sa.String),
    sa.column("created_by", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("voided_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Upgrade schema: 이전 월 예산·사용 기록을 장부로 복사한다."""
    bind = op.get_bind()
    done = set(bind.execute(sa.select(_entries.c.id)).scalars())
    now = datetime.now(UTC)
    rows: list[dict] = []
    owner: dict[str, tuple[str, str]] = {}
    for a in bind.execute(sa.select(_allowances)).all():
        owner[a.id] = (a.group_id, a.child_id)
        if a.budget > 0 and f"mc{a.id}" not in done:
            rows.append(
                {
                    "id": f"mc{a.id}",
                    "group_id": a.group_id,
                    "child_id": a.child_id,
                    "kind": "credit",
                    "amount": a.budget,
                    "memo": "월 용돈 (이전 방식)",
                    "date": f"{a.month}-01",
                    "source": "manual",
                    "plan_due_date": None,
                    "created_by": None,
                    "created_at": now,
                    "voided_at": None,
                }
            )
    for u in bind.execute(sa.select(_uses)).all():
        if u.allowance_id not in owner or u.amount <= 0 or f"mu{u.id}" in done:
            continue
        group_id, child_id = owner[u.allowance_id]
        rows.append(
            {
                "id": f"mu{u.id}",
                "group_id": group_id,
                "child_id": child_id,
                "kind": "use",
                "amount": u.amount,
                "memo": u.memo or "",
                "date": u.date,
                "source": "manual",
                "plan_due_date": None,
                "created_by": None,
                "created_at": now,
                "voided_at": None,
            }
        )
    if rows:
        op.bulk_insert(_entries, rows)


def downgrade() -> None:
    """Downgrade schema. 옮긴 줄은 지우지 않는다(데이터 삭제 금지) — 다음 downgrade 가 장부 테이블을 없앨 때 함께 사라진다."""
