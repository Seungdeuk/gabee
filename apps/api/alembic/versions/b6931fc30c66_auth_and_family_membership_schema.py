"""auth and family membership schema

Revision ID: b6931fc30c66
Revises: 9e28d84c1686
Create Date: 2026-10-22 12:44:04.011243

(2026-10-22, rebase 반영) 원래 355a1a748ec5 바로 위에 만들었으나, PR #11
(billing-care, 리비전 9e28d84c1686)이 같은 부모 위에 먼저 병합되어 멀티 헤드가
생겼다. family_group/shared 코드와는 전혀 겹치지 않아(gabee git diff로 확인)
down_revision만 9e28d84c1686으로 옮겨 단일 체인으로 재배치했다 — DDL 내용은
그대로다.

PR 4-A: 통합 인증·가족 구성원 기능을 위한 스키마 확장(DB만, API 동작은 바뀌지 않는다).
docs/requirements/family-group.md 의 확정 설계를 따른다. 자동 생성 결과를 그대로
쓰지 않고 다음을 직접 손봤다:
  - invites.id 를 참조하는 join_requests/invite_attempts 는 invites.id 가
    NOT NULL+UNIQUE 로 완전히 준비된 뒤에 만들어야 한다(자동 생성은 순서를 몰라서
    테이블을 먼저 만들려고 했다 — FK 생성이 실패했을 것).
  - group_members.role, invites.id 는 기존 행이 있을 수 있어 nullable 로 추가 →
    백필 → NOT NULL 순서를 따른다(자동 생성은 바로 NOT NULL 로 추가하려고 했다).
  - users/invites 의 unnamed UNIQUE 제약은 downgrade 의 drop_constraint() 가
    못 찾으므로 전부 이름을 명시했다.

downgrade() 데이터 손실 경고: 이 리비전 적용 뒤 실제로 로그인/소셜 연동/초대 승인
등(PR 4-B~4-F)을 운영에서 썼다면, downgrade 는 users.login_id/email/
password_hash, group_members.role/family_relation/family_relation_detail/
display_name, invites.id/expires_at/max_uses/use_count 전부와 신규 테이블 7개
(social_accounts, refresh_tokens, password_resets, email_verifications,
member_nicknames, join_requests, invite_attempts)의 모든 데이터를 영구 삭제한다.
실사용 이후에는 downgrade 하지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6931fc30c66"
down_revision: str | Sequence[str] | None = "9e28d84c1686"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. users: 전부 nullable 로 추가 — 기존 익명 계정은 전부 NULL 로 남는다 ---
    op.add_column("users", sa.Column("login_id", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_users_login_id", "users", ["login_id"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    # --- 2. group_members: role/관계/표시이름. role 은 백필 후 NOT NULL ---
    op.add_column("group_members", sa.Column("role", sa.String(length=16), nullable=True))
    op.add_column(
        "group_members", sa.Column("family_relation", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "group_members", sa.Column("family_relation_detail", sa.String(length=40), nullable=True)
    )
    op.add_column("group_members", sa.Column("display_name", sa.String(length=40), nullable=True))

    # 사전 검증: groups.owner_id 전부 group_members 행을 갖고 있는지 확인한다.
    # 비정상 데이터가 있으면 임의로 복구하지 않고 마이그레이션을 중단한다.
    missing_owner = (
        bind.execute(
            sa.text(
                """
            SELECT g.id FROM groups g
            LEFT JOIN group_members gm ON gm.group_id = g.id AND gm.user_id = g.owner_id
            WHERE gm.user_id IS NULL
            """
            )
        )
        .scalars()
        .all()
    )
    if missing_owner:
        raise RuntimeError(
            "다음 그룹은 owner_id 에 해당하는 group_members 행이 없습니다 — "
            f"임의로 복구하지 않고 마이그레이션을 중단합니다: {missing_owner}"
        )

    # 백필: 전부 'member' 로 채운 뒤, groups.owner_id 와 일치하는 행만 'owner' 로 올린다.
    bind.execute(sa.text("UPDATE group_members SET role = 'member' WHERE role IS NULL"))
    bind.execute(
        sa.text(
            """
            UPDATE group_members gm SET role = 'owner'
            FROM groups g WHERE g.id = gm.group_id AND g.owner_id = gm.user_id
            """
        )
    )
    op.alter_column("group_members", "role", nullable=False)
    op.create_index(
        "uq_group_members_one_owner_per_group",
        "group_members",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
        sqlite_where=sa.text("role = 'owner'"),
    )

    # --- 3. invites: id(서로게이트) 는 nullable 로 추가 → 백필 → 검증 → NOT NULL+UNIQUE.
    # use_count 는 0 이 모든 행에 보편적으로 맞는 값이라 server_default 를 그대로 둔다
    # (role 과 달리 행마다 값이 달라지지 않으므로 — role 처럼 백필 후 지울 필요가 없다).
    op.add_column("invites", sa.Column("id", sa.String(length=32), nullable=True))
    op.add_column("invites", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invites", sa.Column("max_uses", sa.Integer(), nullable=True))
    op.add_column(
        "invites",
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
    )

    bind.execute(
        sa.text(
            "UPDATE invites SET id = replace(gen_random_uuid()::text, '-', '') WHERE id IS NULL"
        )
    )
    total = bind.execute(sa.text("SELECT count(*) FROM invites")).scalar()
    distinct_non_null = bind.execute(
        sa.text("SELECT count(DISTINCT id) FROM invites WHERE id IS NOT NULL")
    ).scalar()
    null_count = bind.execute(sa.text("SELECT count(*) FROM invites WHERE id IS NULL")).scalar()
    if null_count or distinct_non_null != total:
        raise RuntimeError(
            f"invites.id 백필 검증 실패(전체 {total}, 고유 {distinct_non_null}, "
            f"NULL {null_count}) — 마이그레이션을 중단합니다."
        )
    op.alter_column("invites", "id", nullable=False)
    op.create_unique_constraint("uq_invites_id", "invites", ["id"])

    # --- 4. 신규 테이블 — invites.id/group_members 가 전부 준비된 뒤에 생성한다 ---
    op.create_table(
        "social_accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_uid", sa.String(length=128), nullable=False),
        sa.Column("email_at_link", sa.String(length=255), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_uid", name="uq_social_provider_uid"),
    )
    op.create_index(
        op.f("ix_social_accounts_user_id"), "social_accounts", ["user_id"], unique=False
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_label", sa.String(length=60), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_resets_token_hash"), "password_resets", ["token_hash"], unique=True
    )
    op.create_index(
        op.f("ix_password_resets_user_id"), "password_resets", ["user_id"], unique=False
    )

    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_email_verifications_token_hash"),
        "email_verifications",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_email_verifications_user_id"), "email_verifications", ["user_id"], unique=False
    )

    op.create_table(
        "member_nicknames",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("target_user_id", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=40), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "owner_user_id"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_member_nicknames_owner_membership",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "target_user_id"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_member_nicknames_target_membership",
        ),
        sa.PrimaryKeyConstraint("group_id", "owner_user_id", "target_user_id"),
    )

    op.create_table(
        "join_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("invite_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["invite_id"], ["invites.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_join_requests_decided_by"), "join_requests", ["decided_by"], unique=False
    )
    op.create_index(op.f("ix_join_requests_group_id"), "join_requests", ["group_id"], unique=False)
    op.create_index(
        op.f("ix_join_requests_invite_id"), "join_requests", ["invite_id"], unique=False
    )
    op.create_index(op.f("ix_join_requests_user_id"), "join_requests", ["user_id"], unique=False)
    op.create_index(
        "uq_join_requests_pending_per_user",
        "join_requests",
        ["group_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "invite_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("invite_id", sa.String(length=32), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invite_id"], ["invites.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invite_attempts_invite_id"), "invite_attempts", ["invite_id"], unique=False
    )
    op.create_index(
        "ix_invite_attempts_ip_created_at", "invite_attempts", ["ip", "created_at"], unique=False
    )
    op.create_index(
        "ix_invite_attempts_user_id_created_at",
        "invite_attempts",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """경고: PR 4-A 이후 생긴 통합 인증·가족 구성원 데이터를 전부 영구 삭제한다 —
    실사용(4-B~4-F 배포) 이후에는 쓰지 않는다. 모듈 docstring 참고."""
    # 자식 테이블(invites.id/group_members 를 참조하는 쪽)부터 먼저 드롭한다.
    op.drop_index("ix_invite_attempts_user_id_created_at", table_name="invite_attempts")
    op.drop_index("ix_invite_attempts_ip_created_at", table_name="invite_attempts")
    op.drop_index(op.f("ix_invite_attempts_invite_id"), table_name="invite_attempts")
    op.drop_table("invite_attempts")

    op.drop_index("uq_join_requests_pending_per_user", table_name="join_requests")
    op.drop_index(op.f("ix_join_requests_user_id"), table_name="join_requests")
    op.drop_index(op.f("ix_join_requests_invite_id"), table_name="join_requests")
    op.drop_index(op.f("ix_join_requests_group_id"), table_name="join_requests")
    op.drop_index(op.f("ix_join_requests_decided_by"), table_name="join_requests")
    op.drop_table("join_requests")

    op.drop_table("member_nicknames")

    op.drop_index(op.f("ix_email_verifications_user_id"), table_name="email_verifications")
    op.drop_index(op.f("ix_email_verifications_token_hash"), table_name="email_verifications")
    op.drop_table("email_verifications")

    op.drop_index(op.f("ix_password_resets_user_id"), table_name="password_resets")
    op.drop_index(op.f("ix_password_resets_token_hash"), table_name="password_resets")
    op.drop_table("password_resets")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_social_accounts_user_id"), table_name="social_accounts")
    op.drop_table("social_accounts")

    # 이제 invites.id 를 참조하는 테이블이 전부 사라졌으니 invites 컬럼을 드롭할 수 있다.
    op.drop_constraint("uq_invites_id", "invites", type_="unique")
    op.drop_column("invites", "use_count")
    op.drop_column("invites", "max_uses")
    op.drop_column("invites", "expires_at")
    op.drop_column("invites", "id")

    op.drop_index(
        "uq_group_members_one_owner_per_group",
        table_name="group_members",
        postgresql_where=sa.text("role = 'owner'"),
        sqlite_where=sa.text("role = 'owner'"),
    )
    op.drop_column("group_members", "display_name")
    op.drop_column("group_members", "family_relation_detail")
    op.drop_column("group_members", "family_relation")
    op.drop_column("group_members", "role")

    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_constraint("uq_users_login_id", "users", type_="unique")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email")
    op.drop_column("users", "login_id")
