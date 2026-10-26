"""가족 프로필·별명·관리자 지정(PR 4-C) 업무 규칙.

- 관계(엄마·아빠·…·기타)와 표시 이름은 **그룹 멤버십별**이고, 본인 것만 바꿀 수 있다(다른 사람 것은 바꿀 수 없다).
- 관리자(owner/admin) 지정·해제는 **owner 만** 한다. owner 는 바꿀 수 없고, owner 로 올리는 값도 받지 않는다(소유권 이전은 범위 밖).
- 별명·메모는 "내가 보는" 라벨이라 작성자 본인에게만 보이고, 구성원끼리만 쓸 수 있다.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.shared.errors import ApiError, bad_request, not_found

from . import profile_repository as prepo
from .models import User
from .profile_schemas import NicknameIn, ProfileIn, RoleIn

DETAIL_MAX = 40
NAME_MAX = 40


def _clean(value: str | None) -> str | None:
    """앞뒤 공백을 지우고 연속 공백을 하나로. 비면 None."""
    text = " ".join((value or "").split())
    return text or None


def _check_length(value: str | None, limit: int, code: str, label: str) -> None:
    if value is not None and len(value) > limit:
        raise bad_request(code, f"{label}은(는) {limit}자 이내로 적어 주세요")


def update_my_profile(db: Session, user: User, group_id: str, body: ProfileIn) -> None:
    """내 멤버십의 표시 이름·관계를 바꾼다(보낸 항목만). 관계가 other 가 아니면 직접 입력한 관계는 지운다."""
    member = prepo.get_membership(db, group_id, user.id)
    if member is None:
        raise ApiError(403, "not_member", "이 가족 그룹의 구성원이 아니에요")
    sent = body.model_fields_set
    if "display_name" in sent:
        name = _clean(body.display_name)
        _check_length(name, NAME_MAX, "invalid_display_name", "이름")
        member.display_name = name
    if "family_relation" in sent:
        member.family_relation = body.family_relation
    if "family_relation_detail" in sent:
        detail = _clean(body.family_relation_detail)
        _check_length(detail, DETAIL_MAX, "invalid_relation_detail", "관계")
        if detail is not None and member.family_relation != "other":
            raise bad_request(
                "relation_detail_needs_other", "관계 직접 입력은 '기타'를 고른 때만 쓸 수 있어요"
            )
        member.family_relation_detail = detail
    if member.family_relation != "other":
        member.family_relation_detail = None  # 다른 관계로 바꾸면 이전 직접 입력은 남기지 않는다
    db.commit()


def change_member_role(
    db: Session, owner: User, group_id: str, target_id: str, body: RoleIn
) -> None:
    """관리자 지정·해제. 소유자(owner)만 할 수 있다."""
    me = prepo.get_membership(db, group_id, owner.id)
    if me is None:
        raise ApiError(403, "not_member", "이 가족 그룹의 구성원이 아니에요")
    if me.role != "owner":
        raise ApiError(403, "not_owner", "가족 소유자만 관리자를 지정할 수 있어요")
    target = prepo.get_membership(db, group_id, target_id)
    if target is None:
        raise not_found("구성원")
    if target.role == "owner":
        raise bad_request("cannot_change_owner", "소유자의 권한은 바꿀 수 없어요")
    if not prepo.set_member_role(db, group_id, target_id, body.role):
        db.rollback()
        raise bad_request("cannot_change_owner", "소유자의 권한은 바꿀 수 없어요")
    db.commit()


def list_my_nicknames(db: Session, user: User, group_id: str):
    return prepo.list_nicknames(db, group_id, user.id)


def set_nickname(db: Session, user: User, group_id: str, target_id: str, body: NicknameIn):
    """내가 다른 구성원에게 붙이는 별명·메모. 둘 다 비우면 지운다(None 반환). 대상은 같은 그룹의 다른 구성원이어야 한다."""
    if target_id == user.id:
        raise bad_request("cannot_nickname_self", "자기 자신에게는 별명을 붙일 수 없어요")
    if prepo.get_membership(db, group_id, user.id) is None:
        raise ApiError(403, "not_member", "이 가족 그룹의 구성원이 아니에요")
    if prepo.get_membership(db, group_id, target_id) is None:
        raise not_found("구성원")  # 다른 그룹 사람은 있는지조차 알려주지 않는다
    nickname = _clean(body.nickname)
    memo = (body.memo or "").strip() or None
    _check_length(nickname, NAME_MAX, "invalid_nickname", "별명")
    if nickname is None and memo is None:
        prepo.delete_nickname(db, group_id, user.id, target_id)
        db.commit()
        return None
    row = prepo.upsert_nickname(db, group_id, user.id, target_id, nickname, memo, datetime.now(UTC))
    db.commit()
    return row
