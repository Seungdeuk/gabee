"""에이전트가 모델에 알려 주는 가족 구성원. 모델은 이름이 아니라 id 만 골라 돌려주고, 코드가 이 가족의 구성원인지 다시 확인한다."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User


@dataclass(frozen=True)
class Member:
    id: str
    name: str  # 실제 이름
    shown: str  # 표시 이름(없으면 빈 문자열)
    relation: str  # 가족 관계 값(mom, dad ... 없으면 빈 문자열)

    @property
    def label(self) -> str:
        return self.shown or self.name


def load(db: Session, group_id: str) -> list[Member]:
    rows = db.execute(
        select(
            GroupMember.user_id, User.name, GroupMember.display_name, GroupMember.family_relation
        )
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.user_id)
    ).all()
    return [
        Member(
            id=user_id,
            name=" ".join((name or "").split()),
            shown=" ".join((display or "").split()),
            relation=relation or "",
        )
        for user_id, name, display, relation in rows
    ]


def names(members: list[Member]) -> list[tuple[str, ...]]:
    """가명화에 쓰는 이름 사전. 구성원마다 (실제 이름, 표시 이름) 묶음 하나이고 첫 번째가 대표 이름이다."""
    people: set[tuple[str, ...]] = set()
    for m in members:
        if m.name:
            people.add((m.name, m.shown) if m.shown and m.shown != m.name else (m.name,))
        elif m.shown:
            people.add((m.shown,))
    return sorted(people)


def line(m: Member) -> str:
    """모델에 보내는 한 줄: id | 표시 이름 | 관계"""
    return f"{m.id} | {m.label} | {m.relation or '-'}"
