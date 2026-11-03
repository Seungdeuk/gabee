"""데일리 체크 저장소: 조회만 하고 commit 은 서비스가 한다(한 요청의 쓰기를 한 트랜잭션으로 묶기 위해).

습관과 응원은 사람(user_id)에게 묶여 그룹 열이 없다. 가족 단위 판단(누가 가족 구성원인가)은 `group_members` 로 한다.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import CheckCheer, CheckItem, CheckSetting


def items_of(db: Session, user_id: str) -> list[CheckItem]:
    """내 습관, 순서대로."""
    return list(
        db.scalars(
            select(CheckItem)
            .where(CheckItem.user_id == user_id)
            .order_by(CheckItem.position, CheckItem.created_at, CheckItem.id)
        )
    )


def item_of(db: Session, user_id: str, item_id: str) -> CheckItem | None:
    return db.scalar(select(CheckItem).where(CheckItem.id == item_id, CheckItem.user_id == user_id))


def max_position(db: Session, user_id: str) -> int | None:
    return db.scalar(select(func.max(CheckItem.position)).where(CheckItem.user_id == user_id))


def shared_items_of(db: Session, user_ids: list[str]) -> list[CheckItem]:
    """가족에게 보이기가 켜진 습관(여러 사람 한 번에). 가족 소속 확인은 호출한 쪽이 한다."""
    if not user_ids:
        return []
    return list(
        db.scalars(
            select(CheckItem)
            .where(CheckItem.user_id.in_(user_ids), CheckItem.shared.is_(True))
            .order_by(CheckItem.user_id, CheckItem.position, CheckItem.created_at, CheckItem.id)
        )
    )


def members_of(db: Session, group_id: str) -> list[tuple[str, str]]:
    """가족 구성원 (user_id, 이름)들, 들어온 순서대로."""
    return [
        (row[0], row[1])
        for row in db.execute(
            select(GroupMember.user_id, User.name)
            .join(User, User.id == GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at, GroupMember.user_id)
        ).all()
    ]


def is_member(db: Session, group_id: str, user_id: str) -> bool:
    return (
        db.scalar(
            select(GroupMember.user_id).where(
                GroupMember.group_id == group_id, GroupMember.user_id == user_id
            )
        )
        is not None
    )


def names_of(db: Session, user_ids: set[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    return dict(db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all())


def cheer_of(db: Session, cheer_id: str) -> CheckCheer | None:
    return db.scalar(select(CheckCheer).where(CheckCheer.id == cheer_id))


def cheers_received(db: Session, user_id: str) -> list[CheckCheer]:
    return list(
        db.scalars(
            select(CheckCheer)
            .where(CheckCheer.to_user_id == user_id)
            .order_by(CheckCheer.sent_at.desc(), CheckCheer.id)
        )
    )


def cheers_sent(db: Session, user_id: str) -> list[CheckCheer]:
    return list(
        db.scalars(
            select(CheckCheer)
            .where(CheckCheer.from_user_id == user_id)
            .order_by(CheckCheer.sent_at.desc(), CheckCheer.id)
        )
    )


def setting_of(db: Session, user_id: str) -> CheckSetting | None:
    return db.get(CheckSetting, user_id)
