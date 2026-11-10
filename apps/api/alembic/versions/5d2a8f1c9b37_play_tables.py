"""play tables

가족 놀이터 테이블 9개를 새로 만든다(expand: 기존 테이블은 건드리지 않는다).

Revision ID: 5d2a8f1c9b37
Revises: 7c1b63d81448
Create Date: 2026-11-05 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d2a8f1c9b37"
down_revision: str | Sequence[str] | None = "7c1b63d81448"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "play_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("game", sa.SmallInteger(), nullable=False),
        sa.Column("maker_id", sa.String(length=32), nullable=False),
        sa.Column("player_ids", sa.JSON(), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["maker_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_play_items_group_id_created_at", "play_items", ["group_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_play_items_maker_id_created_at", "play_items", ["maker_id", "created_at"], unique=False
    )
    op.create_table(
        "play_quiz",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("quiz_no", sa.SmallInteger(), nullable=False),
        sa.Column("qtype", sa.SmallInteger(), nullable=False),
        sa.Column("question", sa.String(length=100), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer", sa.String(length=8), nullable=False),
        sa.Column("comment", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.PrimaryKeyConstraint("play_id", "quiz_no"),
    )
    op.create_table(
        "play_draws",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=False),
        sa.Column("answer", sa.String(length=40), nullable=False),
        sa.Column("alt_answers", sa.JSON(), nullable=True),
        sa.Column("hint2", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.PrimaryKeyConstraint("play_id"),
    )
    op.create_table(
        "play_photos",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=False),
        sa.Column("source", sa.SmallInteger(), nullable=False),
        sa.Column("zoom", sa.SmallInteger(), nullable=False),
        sa.Column("box_x", sa.Float(), nullable=False),
        sa.Column("box_y", sa.Float(), nullable=False),
        sa.Column("question", sa.String(length=20), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer", sa.String(length=4), nullable=False),
        sa.Column("comment", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.PrimaryKeyConstraint("play_id"),
    )
    op.create_table(
        "play_answers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("player_id", sa.String(length=32), nullable=False),
        sa.Column("quiz_no", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("try_no", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("answer", sa.String(length=40), nullable=False),
        sa.Column("is_correct", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hints_used", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "play_id", "player_id", "quiz_no", "try_no", name="uq_play_answers_try"
        ),
    )
    op.create_index(
        "ix_play_answers_play_id_player_id", "play_answers", ["play_id", "player_id"], unique=False
    )
    op.create_table(
        "play_scores",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("player_id", sa.String(length=32), nullable=False),
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("game", sa.SmallInteger(), nullable=False),
        sa.Column("round_no", sa.SmallInteger(), nullable=True),
        sa.Column("reason", sa.SmallInteger(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_play_scores_group_id_created_at",
        "play_scores",
        ["group_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "play_bomb_players",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("player_id", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.ForeignKeyConstraint(["player_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("play_id", "player_id"),
    )
    op.create_table(
        "play_bomb_rounds",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("round_no", sa.SmallInteger(), nullable=False),
        sa.Column("life", sa.SmallInteger(), nullable=False),
        sa.Column("sec", sa.SmallInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("winner_id", sa.String(length=32), nullable=True),
        sa.Column("longest_len", sa.SmallInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["play_id"], ["play_items.id"]),
        sa.ForeignKeyConstraint(["winner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("play_id", "round_no"),
    )
    op.create_table(
        "play_bomb_turns",
        sa.Column("play_id", sa.String(length=32), nullable=False),
        sa.Column("round_no", sa.SmallInteger(), nullable=False),
        sa.Column("turn_seq", sa.SmallInteger(), nullable=False),
        sa.Column("player_id", sa.String(length=32), nullable=False),
        sa.Column("is_say", sa.Boolean(), nullable=False),
        sa.Column("word", sa.String(length=10), nullable=True),
        sa.Column("is_end", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("life", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["play_id", "round_no"],
            ["play_bomb_rounds.play_id", "play_bomb_rounds.round_no"],
        ),
        sa.PrimaryKeyConstraint("play_id", "round_no", "turn_seq"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("play_bomb_turns")
    op.drop_table("play_bomb_rounds")
    op.drop_table("play_bomb_players")
    op.drop_index("ix_play_scores_group_id_created_at", table_name="play_scores")
    op.drop_table("play_scores")
    op.drop_index("ix_play_answers_play_id_player_id", table_name="play_answers")
    op.drop_table("play_answers")
    op.drop_table("play_photos")
    op.drop_table("play_draws")
    op.drop_table("play_quiz")
    op.drop_index("ix_play_items_maker_id_created_at", table_name="play_items")
    op.drop_index("ix_play_items_group_id_created_at", table_name="play_items")
    op.drop_table("play_items")
