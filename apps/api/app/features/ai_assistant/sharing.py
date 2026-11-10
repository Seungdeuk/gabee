"""대화 내용 전달: AI 채팅에서 요약한 글을 사용자가 확인하면 소통 채팅으로 보낸다(docs/requirements/ai_assistant-share.md).

모델은 카드를 만들 뿐 보내지 못한다. 받는 사람은 서버가 찾고, 토큰과 요약문도 서버가 만든다."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_chat import assistant as family_assistant
from app.features.family_group.models import GroupMember, MemberNickname, User
from app.shared.errors import bad_request
from app.shared.high_risk_guard import has_high_risk
from app.shared.llm import proposals

from .family_names import _given_alias

TAB = "ai-assistant"
ACTION = "share_message"
MAX_TEXT = 500
SIGNATURE = "\n\n(가비가 정리해 줬어요)"
FAMILY_WORDS = frozenset({"가족방", "가족전체방", "가족", "가족모두", "다같이", "모두", "전체"})
RELATION_WORDS = {
    "mom": {"엄마", "어머니", "어머님", "모친"},
    "dad": {"아빠", "아버지", "아버님", "부친"},
    "son": {"아들"},
    "daughter": {"딸"},
    "grandma": {"할머니", "할머님"},
    "grandpa": {"할아버지", "할아버님"},
}
RELATION_LABELS = {
    "mom": "엄마",
    "dad": "아빠",
    "son": "아들",
    "daughter": "딸",
    "grandma": "할머니",
    "grandpa": "할아버지",
}


@dataclass(frozen=True)
class Person:
    user_id: str
    label: str  # 화면에 보일 이름. 예: 김영희(엄마)
    nickname: str
    names: frozenset[str]
    relations: frozenset[str]


def _plain(word: str) -> str:
    return "".join(word.split())


def _people(db: Session, group_id: str, me: str) -> list[Person]:
    """나를 뺀 지금 구성원. 나간 사람은 나오지 않는다."""
    nicknames = dict(
        db.execute(
            select(MemberNickname.target_user_id, MemberNickname.nickname).where(
                MemberNickname.group_id == group_id, MemberNickname.owner_user_id == me
            )
        ).all()
    )
    rows = db.execute(
        select(
            User.id,
            User.name,
            GroupMember.display_name,
            GroupMember.family_relation,
            GroupMember.family_relation_detail,
        )
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id, User.id != me)
        .order_by(User.id)
    ).all()
    out = []
    for uid, name, display, relation, detail in rows:
        names = {_plain(n) for n in (name, display) if n}
        names |= {a for a in (_given_alias(n) for n in names) if a}
        words = set(RELATION_WORDS.get(relation or "", set()))
        if detail:
            words.add(_plain(detail))
        shown = display or name or "구성원"
        tag = RELATION_LABELS.get(relation or "") or detail
        out.append(
            Person(
                uid,
                f"{shown}({tag})" if tag else shown,
                _plain(nicknames.get(uid) or ""),
                frozenset(names),
                frozenset(words),
            )
        )
    return out


def find_people(people: list[Person], word: str) -> list[Person]:
    """별명 → 이름 → 가족 관계 순서로 찾는다. 앞 단계에서 찾으면 그 결과를 쓴다."""
    target = _plain(word).removesuffix("님")
    for match in (
        lambda p: p.nickname == target,
        lambda p: target in p.names,
        lambda p: target in p.relations,
    ):
        found = [p for p in people if target and match(p)]
        if found:
            return found
    return []


def propose(db: Session, group_id: str, user: User, args: dict, proposed: list) -> dict:
    """확인 카드를 만든다(아직 보내지 않는다). 받는 사람을 정할 수 없으면 카드 없이 모델이 물어볼 내용을 돌려준다."""
    text = str(args.get("text", "")).strip()
    if not text:
        raise ValueError("보낼 내용이 비어 있어요")
    if len(text) > MAX_TEXT:
        raise ValueError(f"보낼 글은 {MAX_TEXT}자 안으로 줄여 주세요")
    if has_high_risk(text):
        raise ValueError("주민번호·카드·계좌·비밀번호는 전달할 수 없어요")
    to = str(args.get("to", "")).strip()
    member_id = str(args.get("member_id", "") or "").strip()
    people = _people(db, group_id, user.id)
    if member_id:
        found = [p for p in people if p.user_id == member_id]
        if not found:
            raise ValueError("이 가족의 구성원이 아니에요")
        person = found[0]
    elif _plain(to) in FAMILY_WORDS:
        person = None
    else:
        found = find_people(people, to)
        if not found:
            return {
                "need_recipient": True,
                "note": "가족 중에 찾지 못했어요. 누구에게 보낼지 사용자에게 물어보세요. 이름을 지어내지 마세요.",
                "members": [{"member_id": p.user_id, "name": p.label} for p in people],
            }
        if len(found) > 1:
            return {
                "need_recipient": True,
                "note": "해당하는 사람이 여럿이에요. 어느 분인지 사용자에게 물어본 뒤 member_id 로 다시 부르세요.",
                "members": [{"member_id": p.user_id, "name": p.label} for p in found],
            }
        person = found[0]
    place = f"{person.label}에게" if person else "가족 전체방에"
    made = proposals.add(
        proposed,
        TAB,
        ACTION,
        {"peer_id": person.user_id if person else None, "text": text},
        f"{place} 보낼까요?\n{text}",
        user.id,
        group_id,
        key=f"share:{person.user_id if person else 'family'}",
    )
    return {"pending_confirmation": [made.summary]}


def execute(db: Session, group_id: str, user: User, action: str, args: dict) -> None:
    """사용자가 확인한 전달을 실행한다(confirm 에서만 부른다). 받는 사람이 그새 가족을 나갔으면 실패한다."""
    if action != ACTION:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    peer_id = args.get("peer_id")
    if peer_id is not None and not isinstance(peer_id, str):
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    family_assistant.share_as_user(db, user, group_id, str(args["text"]) + SIGNATURE, peer_id)
