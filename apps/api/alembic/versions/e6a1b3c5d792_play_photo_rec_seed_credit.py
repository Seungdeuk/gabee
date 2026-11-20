"""play photo rec seed credit

시드 사진(source 3)에 Pixabay 출처(사진 번호·작성자·페이지·라이선스)를 채운다. 자동 보충이 같은 사진을 다시 받지 않게 하고 출처를 남기기 위함이다.
출처 값은 alembic/seed_data/photo_rec/credits.json 에 있다. 비어 있는 칸만 채우고, 이미 값이 있으면 건드리지 않는다. downgrade 는 이 값을 비운다.

Revision ID: e6a1b3c5d792
Revises: d4f7a2b8c351
Create Date: 2026-11-19 17:30:00.000000

"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6a1b3c5d792"
down_revision: str | Sequence[str] | None = "d4f7a2b8c351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDITS = Path(__file__).resolve().parents[1] / "seed_data" / "photo_rec" / "credits.json"

rec = sa.table(
    "play_photo_rec",
    sa.column("id", sa.String),
    sa.column("source", sa.SmallInteger),
    sa.column("external_id", sa.String),
    sa.column("credit_user", sa.String),
    sa.column("credit_url", sa.String),
    sa.column("license", sa.String),
)


def upgrade() -> None:
    credits = json.loads(CREDITS.read_text(encoding="utf-8"))
    for key, c in credits.items():
        op.execute(
            rec.update()
            .where((rec.c.id == f"seed{key}") & (rec.c.source == 3) & rec.c.external_id.is_(None))
            .values(
                external_id=c["external_id"],
                credit_user=c["credit_user"],
                credit_url=c["credit_url"],
                license=c["license"],
            )
        )


def downgrade() -> None:
    op.execute(
        rec.update()
        .where((rec.c.source == 3) & rec.c.id.like("seed%"))
        .values(external_id=None, credit_user=None, credit_url=None, license=None)
    )
