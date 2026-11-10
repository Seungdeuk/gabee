"""가족 이름 메타데이터화: 올린 문서 속 가족 이름을 `[가족:<user_id>]` 자리표시로 바꿔 저장하고, 읽을 때 현재 이름으로 되돌린다.

왜: 정규식 가리기는 `성명: 강민훈` 을 `강**` 로 바꿔서 강민훈·강민수를 구분할 수 없게 만든다. 가리기 **전에** 가족 구성원
이름을 user_id 자리표시로 바꾸면 (1) 누구 이야기인지 남고 (2) 분류(외부 서비스로 나갈 수 있음)·저장에 가족 실명이 들어가지
않으며 (3) 이름을 바꾸거나 구성원이 나가도 읽을 때 현재 이름으로 보인다.

이름 찾기는 `shared/privacy/detectors.py` 의 검증된 `_detect_person_known`(낱말 속 오탐 방지, 조사 허용, 성 뗀 이름 별칭)을
그대로 쓴다. 이 모듈이 더하는 것은 "찾은 글자가 어느 구성원인가" 를 정하는 일이고, 같은 글자가 둘 이상의 구성원에 해당하면
(동명이인, 두 사람의 이름이 같은 이름자를 가진 경우) **치환하지 않는다**: 임의로 고르면 남의 기록이 되기 때문이다. 그 글자는
원래대로 남아 뒤의 정규식 가리기(`강**`)를 받는다. 가족 호칭(엄마·아빠 …)은 이름이 아니라서 치환하지 않는다.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User
from app.shared.privacy.detectors import (
    _FOLD,
    KINSHIP_TERMS,
    SURNAMES,
    _detect_person_known,
    _is_hangul,
)

TAG_RE = re.compile(r"\[가족:([0-9A-Za-z_-]{1,64})\]")
# 업로드에서 읽은 이름이 가족 이름과 한 글자 차이일 때(OCR 오독일 수 있음) 같은 사람인지 사용자에게 물어볼 때까지 남기는 표시.
# 글자 자체는 저장하지 않고 후보 가족의 user_id 만 둔다(가린 값을 남기지 않는 원칙)
CHECK_RE = re.compile(r"\[확인필요:([0-9A-Za-z_-]{1,64})\]")
CHECK_SHOWN = "[이름 확인 필요]"
NEUTRAL_NAME = "가족 구성원"  # 이미 나갔거나 모르는 id 를 보일 때

# 가리기(정규식)가 자리표시 속 user_id 의 숫자 덩어리를 번호로 오인하지 않게, 가리는 동안만 짧은 임시 표식으로 바꿔 둔다
_OPEN, _CLOSE = "", ""
_TEMP_RE = re.compile(f"{_OPEN}(\\d+){_CLOSE}")


@dataclass(frozen=True)
class Member:
    """가족 그룹 구성원 한 명. shown 은 앱에서 보이는 이름(표시 이름이 있으면 그것, 없으면 실제 이름)."""

    user_id: str
    name: str
    display_name: str | None = None

    @property
    def shown(self) -> str:
        return " ".join((self.display_name or "").split()) or " ".join(self.name.split())

    @property
    def spellings(self) -> set[str]:
        """이 사람을 부르는 글자들(실제 이름·표시 이름). 한 글자 이하는 이름으로 쓰지 않는다."""
        found = {" ".join(x.split()) for x in (self.name, self.display_name or "")}
        return {s for s in found if len(s) >= 2}


def load_members(db: Session, group_id: str) -> list[Member]:
    """이 그룹 구성원의 (user_id, 이름, 표시 이름). family_chat 의 `member_names` 는 user_id 가 없어서 따로 둔다."""
    rows = db.execute(
        select(User.id, User.name, GroupMember.display_name)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.id)
    ).all()
    return [Member(uid, name or "", display) for uid, name, display in rows]


def _given_alias(spelling: str) -> str | None:
    """성 + 두 글자 이름이면 이름만 부르는 말('강민훈' -> '민훈'). detectors 의 별칭 규칙과 같다."""
    if len(spelling) == 3 and spelling[0] in SURNAMES and all(_is_hangul(c) for c in spelling):
        return spelling[1:]
    return None


def _owners(members: list[Member]) -> dict[str, set[str]]:
    """글자 -> 그 글자로 불릴 수 있는 구성원 user_id 들. 둘 이상이면 동명이인(치환하지 않는다)."""
    owners: dict[str, set[str]] = {}
    for m in members:
        for s in m.spellings:
            if s in KINSHIP_TERMS:
                continue
            owners.setdefault(s, set()).add(m.user_id)
    for m in members:  # 성 뗀 이름자는 다른 사람의 표기와 겹칠 수 있어서 모두 모은 뒤에 더한다
        for s in m.spellings - KINSHIP_TERMS:
            alias = _given_alias(s)
            if alias:
                owners.setdefault(alias, set()).add(m.user_id)
    return owners


class FamilyTagger:
    """한 가족 그룹의 구성원 사전으로 글 속 이름을 `[가족:<user_id>]` 로 바꾼다. 문서 한 건 처리마다 하나를 만든다."""

    def __init__(self, members: list[Member]):
        self._owners = _owners(members)
        # 탐지기에는 표기 그대로만 준다: 성 뗀 이름자 별칭은 탐지기가 일반어('하나' 등)를 걸러 가며 직접 만든다
        self._known = tuple(sorted({s for m in members for s in m.spellings} - KINSHIP_TERMS))
        self._ids: list[str] = []  # 가리는 동안 쓰는 임시 표식 번호 -> user_id

    def _slot(self, user_id: str) -> str:
        if user_id not in self._ids:
            self._ids.append(user_id)
        return f"{_OPEN}{self._ids.index(user_id)}{_CLOSE}"

    def protect(self, text: str) -> str:
        """(1) 이미 있는 자리표시와 (2) 글 속 가족 이름을 임시 표식으로 바꾼다. 정규식 가리기 **전에** 부른다.
        끝나면 `expand` 로 `[가족:<id>]` 로 펼친다."""
        if not text:
            return text
        text = TAG_RE.sub(lambda m: self._slot(m.group(1)), text)
        if not self._known:
            return text
        folded = text.translate(_FOLD)  # 전각 글자도 찾되 길이는 그대로라 위치가 맞는다
        spans = sorted(_detect_person_known(folded, self._known), key=lambda s: (s.start, -s.end))
        out, pos = [], 0
        for s in spans:
            if s.start < pos:  # 겹치면 먼저 시작한(같으면 긴) 것만
                continue
            owners = self._owners.get(" ".join(folded[s.start : s.end].split()), set())
            if len(owners) != 1:  # 동명이인·알 수 없음: 임의로 고르지 않는다
                continue
            out.append(text[pos : s.start])
            out.append(self._slot(next(iter(owners))))
            pos = s.end
        out.append(text[pos:])
        return "".join(out)

    def expand(self, text: str) -> str:
        """임시 표식을 `[가족:<user_id>]` 로 펼친다."""
        return _TEMP_RE.sub(lambda m: f"[가족:{self._ids[int(m.group(1))]}]", text)

    def tag(self, text: str) -> str:
        """가리기 없이 이름만 자리표시로 바꾼다(제목처럼 따로 가리지 않는 글)."""
        return self.expand(self.protect(text))

    def near_member(self, spelling: str) -> str | None:
        """가족 이름과 글자가 같지는 않지만 한 글자 차이인 이름이면 그 구성원의 user_id. 딱 한 명일 때만(여럿이면 None).
        OCR 이 이름을 한 글자 틀리게 읽은 경우를 잡는다. 가족 호칭(엄마·아빠 …)은 이름이 아니라서 제외한다."""
        q = " ".join((spelling or "").split())
        if len(q) < 2 or q in self._owners or q in KINSHIP_TERMS:
            return None
        found = {uid for s, uids in self._owners.items() if _within_one_edit(q, s) for uid in uids}
        return next(iter(found)) if len(found) == 1 else None

    def candidates(self, text: str) -> list["Candidate"]:
        """글 속에서 가족 이름과 글자가 같은 자리(후보)를 시작 위치 순으로 찾는다. 뜻은 판단하지 않는다 — 그건 호출한 쪽(Claude)이 문맥으로 한다.
        동명이인(같은 글자가 둘 이상의 구성원에 해당)은 후보로 삼지 않는다(임의로 고르지 않는다). 겹치면 먼저 시작한(같으면 긴) 것만."""
        if not text or not self._known:
            return []
        folded = text.translate(_FOLD)  # 전각 글자도 찾되 길이는 그대로라 위치가 맞는다
        spans = sorted(_detect_person_known(folded, self._known), key=lambda s: (s.start, -s.end))
        out: list[Candidate] = []
        pos = 0
        for s in spans:
            if s.start < pos:
                continue
            owners = self._owners.get(" ".join(folded[s.start : s.end].split()), set())
            if len(owners) != 1:
                continue
            out.append(Candidate(s.start, s.end, next(iter(owners)), text[s.start : s.end]))
            pos = s.end
        return out


@dataclass(frozen=True)
class Candidate:
    """가족 이름 후보 한 자리. [start, end) 는 글 안의 위치, user_id 는 그 이름의 주인."""

    start: int
    end: int
    user_id: str
    spelling: str


def extract_ids(*texts: str) -> list[str]:
    """글들에 들어 있는 자리표시의 user_id (처음 나온 순서, 중복 없음)."""
    seen: dict[str, None] = {}
    for text in texts:
        for m in TAG_RE.finditer(text or ""):
            seen.setdefault(m.group(1), None)
    return list(seen)


def clip(text: str, limit: int) -> str:
    """limit 글자로 자르되 `[가족:…]` 자리표시를 반으로 자르지 않는다(반쪽 자리표시는 되돌릴 수 없다)."""
    cut = text[:limit]
    start = cut.rfind("[가족:")
    if start != -1 and "]" not in cut[start:]:
        cut = cut[:start].rstrip()
    return cut


def shown_names(members: list[Member]) -> dict[str, str]:
    """user_id -> 현재 보이는 이름."""
    return {m.user_id: m.shown for m in members if m.shown}


def restore(text: str, names: dict[str, str]) -> str:
    """`[가족:<id>]` 를 현재 이름으로 바꾼다. 나간 구성원·모르는 id 는 중립 문구('가족 구성원'). 확인 대기 표시는 '[이름 확인 필요]'."""
    if not text:
        return text
    if "[확인필요:" in text:
        text = CHECK_RE.sub(CHECK_SHOWN, text)
    if "[가족:" not in text:
        return text
    return TAG_RE.sub(lambda m: names.get(m.group(1), NEUTRAL_NAME), text)


def check_ids(text: str) -> list[str]:
    """글에 남은 확인 대기 표시의 후보 user_id (처음 나온 순서, 중복 없음)."""
    return list(dict.fromkeys(CHECK_RE.findall(text or "")))


def resolve_check(text: str, user_id: str, same_person: bool) -> str:
    """확인 대기 표시를 답에 따라 바꾼다: 같은 사람이면 `[가족:<id>]`, 아니면 `[이름]`."""
    new = f"[가족:{user_id}]" if same_person else "[이름]"
    return text.replace(f"[확인필요:{user_id}]", new)


def family_of(user_ids: list[str] | None, names: dict[str, str]) -> list[str]:
    """기록에 등장한 가족의 현재 이름들(이미 나간 사람은 뺀다)."""
    return list(dict.fromkeys(names[u] for u in user_ids or [] if u in names))


def match_member(members: list[Member], query: str) -> list[str]:
    """이름·표시 이름·(성 뗀) 이름자로 구성원 user_id 를 찾는다. 같은 글자가 여럿이면 모두 돌려준다(호출한 쪽이 알린다)."""
    q = " ".join((query or "").split())
    if not q:
        return []
    found: dict[str, None] = {}
    for m in members:
        for s in m.spellings:
            if q == s or q == _given_alias(s):
                found.setdefault(m.user_id, None)
    return list(found)


def _within_one_edit(a: str, b: str) -> bool:
    """두 글자열이 한 글자 바꿈·넣음·뺌 이내로 같은가('민혼' ~ '민훈')."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


def suggest_members(members: list[Member], query: str) -> list[str]:
    """찾지 못한 이름과 한 글자 차이인 구성원의 보이는 이름(오타 후보). 자동으로 같은 사람이라 정하지 않고 안내에만 쓴다."""
    q = " ".join((query or "").split())
    if len(q) < 2:
        return []
    found: list[str] = []
    for m in members:
        cands = set(m.spellings) | {a for a in map(_given_alias, m.spellings) if a}
        if any(len(c) >= 2 and _within_one_edit(q, c) for c in cands) and m.shown not in found:
            found.append(m.shown)
    return found
