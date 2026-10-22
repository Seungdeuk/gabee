import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def now() -> datetime:
    return datetime.now(UTC)


def _uid() -> str:
    """기존 repository/service 의 id 생성 방식(uuid4 hex 앞 12자리)과 동일하게 맞춘다."""
    return uuid.uuid4().hex[:12]


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(16), default="child")  # parent | child | other
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    # 통합 인증(PR 4-A, 스키마만 — 가입/로그인 로직은 PR 4-B). 익명 계정은 전부 null로 유지된다.
    login_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # 이름을 명시하지 않으면 Alembic autogenerate 가 downgrade 에서 drop_constraint()
        # 를 못 만든다(이름 없는 제약은 나중에 못 찾음) — 전부 명시적으로 이름을 둔다.
        UniqueConstraint("login_id", name="uq_users_login_id"),
        UniqueConstraint("email", name="uq_users_email"),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GroupMember(Base):
    """group_id 당 role='owner' 는 최대 1명(부분 유니크 인덱스). 최소 1명(owner 존재)은
    DB 제약이 아니라 서비스 계층 불변식이다 — repository.add_group() 이 그룹 생성과
    owner 멤버십을 같은 트랜잭션에서 만든다(role="owner" 명시). 향후(4-E) owner 를
    지우거나 바꾸는 기능을 추가할 때도 "마지막 owner 삭제 금지"를 서비스에서 지켜야 한다."""

    __tablename__ = "group_members"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    # 가족 관리자·관계·표시 이름(PR 4-A, 스키마만 — 지정/수정 API 는 PR 4-E).
    # role 의 Python 기본값은 "member" 뿐이다(DB server_default 는 쓰지 않는다 — 기존
    # 행 백필은 Alembic 마이그레이션의 명시적 UPDATE 로 한다). 그룹 생성자(owner)는
    # repository.add_group() 이 role="owner" 를 직접 넘겨서 이 기본값을 덮어쓴다.
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner | admin | member
    family_relation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # mom|dad|son|daughter|grandma|grandpa|other
    family_relation_detail: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index(
            "uq_group_members_one_owner_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
            sqlite_where=text("role = 'owner'"),
        ),
    )


class Invite(Base):
    __tablename__ = "invites"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    # 초대 보안 강화(PR 4-A, 스키마만 — 승인·레이트리밋 로직은 PR 4-D).
    # id 는 PK 가 아니다(code 가 여전히 PK) — join_requests/invite_attempts 가 코드
    # 원문 대신 참조할 서로게이트 식별자. default=_uid 라서 repository.add_group() 이
    # Invite(...) 를 만들 때 id 를 안 넘겨도(기존 호출부 그대로) INSERT 가 성공한다.
    id: Mapped[str] = mapped_column(String(32), nullable=False, default=_uid)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("id", name="uq_invites_id"),)


class SocialAccount(Base):
    """Google/Kakao 연동(PR 4-C). 같은 provider_uid 를 두 계정이 동시에 못 가져간다."""

    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16))  # google | kakao
    provider_uid: Mapped[str] = mapped_column(String(128))
    email_at_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (UniqueConstraint("provider", "provider_uid", name="uq_social_provider_uid"),)


class RefreshToken(Base):
    """Access/Refresh 세션(PR 4-B). 토큰 원문은 저장하지 않고 해시만 둔다."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(60), nullable=True)


class PasswordReset(Base):
    """비밀번호 재설정(PR 4-B). 토큰 원문은 저장하지 않고 해시만 둔다."""

    __tablename__ = "password_resets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailVerification(Base):
    """이메일 인증(PR 4-B). 토큰 원문은 저장하지 않고 해시만 둔다."""

    __tablename__ = "email_verifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemberNickname(Base):
    """내가 다른 구성원에게 붙이는 개인별 별명·메모(PR 4-E). owner_user_id(별명을 쓴
    사람) 기준으로만 조회·수정한다 — 서비스 계층에서 요청자와 비교한다.

    group_id+owner_user_id, group_id+target_user_id 둘 다 users.id 가 아니라
    group_members(group_id, user_id) 를 참조하는 복합 FK 다 — 그룹에 실제로 속한
    사용자만 별명을 쓰거나 대상이 될 수 있도록 DB 레벨에서 강제한다."""

    __tablename__ = "member_nicknames"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    target_user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(String(40), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "owner_user_id"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_member_nicknames_owner_membership",
        ),
        ForeignKeyConstraint(
            ["group_id", "target_user_id"],
            ["group_members.group_id", "group_members.user_id"],
            name="fk_member_nicknames_target_membership",
        ),
    )


class JoinRequest(Base):
    """초대코드 검증 후 관리자 승인 대기(PR 4-D). 승인 전에는 group_members 행을
    만들지 않으므로 PR 3 의 ensure_group_member() 가 그대로 접근을 막아준다."""

    __tablename__ = "join_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    invite_id: Mapped[str] = mapped_column(ForeignKey("invites.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    __table_args__ = (
        Index(
            "uq_join_requests_pending_per_user",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


class InviteAttempt(Base):
    """초대코드 레이트리밋(PR 4-D). 실패한 코드 원문·해시를 저장하지 않는다 —
    매칭에 성공했을 때만 invite_id 를 채운다."""

    __tablename__ = "invite_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    ip: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    invite_id: Mapped[str | None] = mapped_column(
        ForeignKey("invites.id"), nullable=True, index=True
    )
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        Index("ix_invite_attempts_ip_created_at", "ip", "created_at"),
        Index("ix_invite_attempts_user_id_created_at", "user_id", "created_at"),
    )
