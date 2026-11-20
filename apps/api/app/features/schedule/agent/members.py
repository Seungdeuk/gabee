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


def same_call(members: list[Member], text: str, me: str) -> list[Member]:
    """문장에서 가리킨 호칭(예: 삼촌)이 둘 이상의 가족 표시 이름에 들어 있으면 그 가족들. 없으면 빈 목록."""
    others = [m for m in members if m.id != me and m.label]
    best: list[Member] = []
    best_len = 0
    for token in text.split():
        for size in range(len(token), 1, -1):
            part = token[:size]
            found = [m for m in others if part in m.label]
            if len(found) >= 2:
                if size > best_len:
                    best, best_len = found, size
                break
    return best


def ask_text(members: list[Member], text: str, me: str, fallback: str) -> str:
    """같은 호칭의 가족이 여럿이면 저장된 이름으로 후보를 보여 주며 묻는다. 후보를 못 찾으면 fallback."""
    found = same_call(members, text, me)
    if not found:
        return fallback
    labels = [m.label for m in found]
    shown = [
        f"{m.label}({m.name})"
        if labels.count(m.label) > 1 and m.name and m.name != m.label
        else m.label
        for m in found
    ]
    return f"비슷한 이름의 가족이 {len(found)}분 있어요. 누구인가요? ({', '.join(shown)})"
