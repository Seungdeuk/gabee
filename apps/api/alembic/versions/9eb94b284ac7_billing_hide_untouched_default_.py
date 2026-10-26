"""billing hide untouched default subscriptions

Revision ID: 9eb94b284ac7
Revises: 8a21dd425a73
Create Date: 2026-10-23 22:00:00.000000

예전에는 구독 탭을 처음 열 때 기본 항목 5개(넷플릭스·유튜브 프리미엄·디즈니+·가족 결합 할인·요금제 결합 할인)를
자동으로 만들었다. 이제는 서비스 목록에서 골라 추가하므로, 이미 만들어진 그룹의 **아무도 손대지 않은** 기본 항목만
소프트 삭제(`deleted_at`)로 감춘다. 행은 지우지 않는다(UPDATE 만).
손댄 항목은 건드리지 않는다: 상태가 바뀌었거나, 금액·할인·결제일·통신사·결제한 사람이 있거나, 나눌 사람을 정했으면 남긴다.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9eb94b284ac7"
down_revision: str | Sequence[str] | None = "8a21dd425a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS = (
    ("ott", "넷플릭스"),
    ("ott", "유튜브 프리미엄"),
    ("ott", "디즈니+"),
    ("telecom", "가족 결합 할인"),
    ("telecom", "요금제 결합 할인"),
)

_items = sa.table(
    "subscription_items",
    sa.column("id", sa.String),
    sa.column("kind", sa.String),
    sa.column("name", sa.String),
    sa.column("status", sa.String),
    sa.column("carrier", sa.String),
    sa.column("monthly_fee", sa.Integer),
    sa.column("discount_amount", sa.Integer),
    sa.column("billing_day", sa.Integer),
    sa.column("payer_id", sa.String),
    sa.column("split_among", sa.JSON),
    sa.column("deleted_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Upgrade schema: 손대지 않은 기본 구독 항목을 소프트 삭제한다."""
    bind = op.get_bind()
    now = datetime.now(UTC)
    rows = bind.execute(
        sa.select(_items.c.id, _items.c.kind, _items.c.name, _items.c.split_among).where(
            _items.c.deleted_at.is_(None),
            _items.c.status == "check",
            _items.c.carrier.is_(None),
            _items.c.monthly_fee.is_(None),
            _items.c.discount_amount.is_(None),
            _items.c.billing_day.is_(None),
            _items.c.payer_id.is_(None),
        )
    ).all()
    # split_among 은 JSON 이라 파이썬에서 비어 있는지 확인한다(기본값은 빈 목록)
    ids = [r.id for r in rows if (r.kind, r.name) in _DEFAULTS and not r.split_among]
    if ids:
        bind.execute(sa.update(_items).where(_items.c.id.in_(ids)).values(deleted_at=now))


def downgrade() -> None:
    """Downgrade schema. 감춘 항목은 되살리지 않는다(어떤 항목을 이 리비전이 감췄는지 따로 기록하지 않았다)."""
