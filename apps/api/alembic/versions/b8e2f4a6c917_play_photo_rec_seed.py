"""play photo rec seed

찰칵! 탐정단 가비 추천의 흔한 사진 시드(사진 + 질문·보기·정답·확대 위치)를 play_photo_rec 에 넣는다.
사진과 seed.json 은 alembic/seed_data/photo_rec/ 에 있고(서버 이미지에 alembic 폴더가 같이 들어간다) 이 시점 내용으로 고정된다.
이미 있는 행(id `seed<번호>`)은 건드리지 않아 여러 번 실행돼도 안전하다. 이후 문제를 고치거나 늘릴 때는
scripts/seed_photo_rec.py 로 하거나 새 마이그레이션을 만든다. downgrade 는 이 시드 행만 지운다.

Revision ID: b8e2f4a6c917
Revises: a7d3c91e5b84
Create Date: 2026-11-19 15:00:00.000000

"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8e2f4a6c917"
down_revision: str | Sequence[str] | None = "a7d3c91e5b84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_SEED = 3  # 흔한 사진(시드)
SEED_DIR = Path(__file__).resolve().parents[1] / "seed_data" / "photo_rec"

rec = sa.table(
    "play_photo_rec",
    sa.column("id", sa.String),
    sa.column("group_id", sa.String),
    sa.column("source", sa.SmallInteger),
    sa.column("attachment_id", sa.String),
    sa.column("image", sa.LargeBinary),
    sa.column("kind", sa.SmallInteger),
    sa.column("usable", sa.Boolean),
    sa.column("question", sa.String),
    sa.column("options", sa.JSON),
    sa.column("answer", sa.String),
    sa.column("box_x", sa.Float),
    sa.column("box_y", sa.Float),
    sa.column("zoom", sa.SmallInteger),
    sa.column("prompt_version", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Upgrade data."""
    items = json.loads((SEED_DIR / "seed.json").read_text(encoding="utf-8"))
    conn = op.get_bind()
    have = {r[0] for r in conn.execute(sa.select(rec.c.id).where(rec.c.source == SOURCE_SEED))}
    now = datetime.now(UTC)
    rows = []
    for it in items:
        row_id = f"seed{it['key']}"
        if row_id in have:
            continue
        options = it["options"]
        rows.append(
            {
                "id": row_id,
                "group_id": None,
                "source": SOURCE_SEED,
                "attachment_id": None,
                "image": (SEED_DIR / it["image"]).read_bytes(),
                "kind": it["kind"],
                "usable": True,
                "question": it["question"],
                "options": options,
                "answer": "".join(
                    "1" if i == it["answer_index"] else "0" for i in range(len(options))
                ),
                "box_x": float(it["box_x"]),
                "box_y": float(it["box_y"]),
                "zoom": it["zoom"],
                "prompt_version": "seed",
                "created_at": now,
            }
        )
    if rows:
        op.bulk_insert(rec, rows)


def downgrade() -> None:
    """Downgrade data: 시드로 넣은 행만 지운다."""
    op.execute(rec.delete().where((rec.c.source == SOURCE_SEED) & rec.c.id.like("seed%")))
