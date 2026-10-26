"""요청 단위 가명화기. 원본 값과 토큰의 대응표는 이 객체의 메모리에만 있다.

- DB·로그·캐시·응답에 대응표를 저장하거나 담지 않는다(이 모듈은 logging 을 쓰지 않는다).
- ``with Pseudonymizer() as pz:`` 로 쓰면 블록이 끝날 때(예외 포함) 대응표 참조를 지운다. 파이썬 객체의 참조를 끊을 뿐
  메모리에서 물리적으로 완전히 지워진다고 보장하지 않는다.
- BLOCK 대상 값(비밀번호·주민번호·카드·계좌)은 대응표에 넣지 않는다. 복원할 수 없다.
- 복원은 **이 요청이 만든 토큰만** 한다. 모델이 지어내거나 변형한 토큰(``[PHONE_9]``, ``[phone_1]``, ``[PHONE_ 1]``, 전각 괄호
  ``【PHONE_1】``)은 그대로 두고 unknown 으로 알려 준다.
- 사용자가 대화에 직접 쓴 토큰 모양(``[PHONE_1]``, 대소문자·공백·전각 괄호 변형 포함)과 대응표에 넣는 값(발화자 이름 등)이
  토큰 모양이면 ``‹PHONE_1›`` 로 바꿔 복원 대상이 되지 않게 한다(남의 값으로 복원되거나 두 번 복원되는 것을 막는다).
- 토큰 후보는 길이가 제한된 괄호(32자 이하)만 보고 안쪽은 코드로 검사한다(정규식 역추적 폭주 방지).
"""

import re
from dataclasses import dataclass, field

from .detectors import detect
from .policy import BLOCKED_PLACEHOLDER, Action, Policy
from .types import Kind, Span

# 토큰 이름(복원 가능한 종류)
_TOKEN_NAME: dict[Kind, str] = {
    Kind.PHONE: "PHONE",
    Kind.EMAIL: "EMAIL",
    Kind.ADDRESS: "ADDR",
    Kind.PERSON: "PERSON",
}
# 정책이 MASK 여도 대응표에 넣지 않는(복원 불가) 종류
_NEVER_STORE = frozenset({Kind.SECRET, Kind.RRN, Kind.CARD, Kind.ACCOUNT})
_NEVER_STORE_TOKEN = {
    Kind.SECRET: "[SECRET]",
    Kind.RRN: "[RRN]",
    Kind.CARD: "[CARD]",
    Kind.ACCOUNT: "[ACCOUNT]",
}
_FIXED_TOKENS = frozenset(_NEVER_STORE_TOKEN.values())

# 복원 대상이 아닌 종류의 토큰을 응답에서 바꿔 넣는 일반화 문구
GENERIC_TEXT: dict[Kind, str] = {
    Kind.PHONE: "(연락처)",
    Kind.EMAIL: "(이메일)",
    Kind.ADDRESS: "(주소)",
    Kind.PERSON: "(사람)",
}
UNKNOWN_TEXT = "(알 수 없는 항목)"
SENSITIVE_TEXT = "(민감 정보)"

_ALL_NAMES = "PHONE|EMAIL|ADDR|PERSON|SECRET|RRN|CARD|ACCOUNT"
# 괄호(반각·전각·【】)로 감싼 짧은 글자만 후보로 잡는다. 안쪽 길이 제한 때문에 입력 길이에 선형이다.
_BRACKETED = re.compile(r"[\[［【][^\[\]［］【】\n]{0,32}[\]］】]")
# 안쪽이 토큰 모양인지(대소문자·공백·0 채움·전각 숫자 변형 포함). 최대 32자 문자열에만 쓴다.
_INNER = re.compile(rf"\s*(?:{_ALL_NAMES})[\s_]*[0-9０-９]*\s*", re.IGNORECASE)


def _tokenish(raw: str) -> bool:
    return bool(_INNER.fullmatch(raw[1:-1]))


_NEUTRALIZED = re.compile(r"‹[^‹›\n]{0,32}›")


def scrub_leftovers(text: str) -> str:
    """응답에 남은 무력화 토큰(``‹PERSON_2›``: 사용자가 대화에 직접 쓴 토큰 모양)과 복원 불가 고정 토큰(``[RRN]`` 등)을
    일반 문구로 바꾼다. 사용자에게 보이는 글자에서 토큰 모양이 그대로 나오지 않게 하는 후처리다."""
    for fixed in _FIXED_TOKENS:
        text = text.replace(fixed, SENSITIVE_TEXT)
    return _NEUTRALIZED.sub(
        lambda m: UNKNOWN_TEXT if _tokenish("[" + m.group(0)[1:-1] + "]") else m.group(0), text
    )


@dataclass(frozen=True)
class MaskResult:
    """apply 결과. text 는 외부로 보내도 되는 글자, counts_by_kind 는 종류별 탐지 수, blocked 는 메시지 차단 여부."""

    text: str
    counts_by_kind: dict[str, int] = field(default_factory=dict)
    blocked: bool = False


@dataclass(frozen=True)
class RestoreResult:
    """restore 결과. restored_tokens 는 복원한 토큰, generalized_tokens 는 복원 대상 종류가 아니라 일반화 문구로 바꾼 토큰,
    unknown_tokens 는 이 요청이 만들지 않아 복원하지 않은 토큰 모양."""

    text: str
    restored_tokens: list[str] = field(default_factory=list)
    unknown_tokens: list[str] = field(default_factory=list)
    generalized_tokens: list[str] = field(default_factory=list)


def _norm_key(kind: Kind, value: str) -> str:
    if kind is Kind.PHONE:
        return re.sub(r"\D", "", value)
    if kind is Kind.EMAIL:
        return value.lower()
    return " ".join(value.split())


def _neutralize(text: str) -> str:
    """토큰 모양('[PHONE_1]', '[phone_1]', '[PHONE_01]', '【PHONE_1】')을 다른 괄호로 바꿔 복원 대상이 되지 않게 한다."""
    return _BRACKETED.sub(
        lambda m: "‹" + m.group(0)[1:-1] + "›" if _tokenish(m.group(0)) else m.group(0), text
    )


class Pseudonymizer:
    """한 요청 안에서만 쓰는 가명화기. 같은 원본 값은 같은 토큰을 받고 번호는 처음 나온 순서다."""

    __slots__ = ("_aliases", "_closed", "_counters", "_forward", "_kind", "_reverse")

    def __init__(self) -> None:
        self._forward: dict[tuple[Kind, str], str] = {}  # (종류, 정규화 값) -> 토큰
        self._reverse: dict[str, str] = {}  # 토큰 -> 원본 값
        self._kind: dict[str, Kind] = {}  # 토큰 -> 종류
        self._counters: dict[Kind, int] = {}
        self._closed = False
        self._aliases: dict[
            str, str
        ] = {}  # 같은 사람의 다른 표기(표시 이름) -> 대표 이름. PERSON 토큰 키를 하나로 묶는다

    def set_aliases(self, aliases: dict[str, str]) -> None:
        """같은 사람의 다른 표기를 대표 이름으로 묶는다(예: 표시 이름 '수진이' -> 실제 이름 '이수진'). PERSON 토큰에만 쓰인다."""
        self._aliases = {
            " ".join(k.split()): " ".join(v.split()) for k, v in aliases.items() if k and v
        }

    # ----- 수명 -----
    def __enter__(self) -> "Pseudonymizer":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.clear()
        return False  # 예외는 삼키지 않는다

    def clear(self) -> None:
        """대응표 참조를 지우고 이 객체를 닫는다. 닫은 뒤에는 apply 가 막히고 restore 는 아무것도 복원하지 않는다."""
        self._forward.clear()
        self._reverse.clear()
        self._kind.clear()
        self._counters.clear()
        self._aliases.clear()
        self._closed = True

    @property
    def size(self) -> int:
        """대응표에 든 토큰 수(값은 노출하지 않는다)."""
        return len(self._reverse)

    # ----- 값이 새지 않도록 -----
    def __repr__(self) -> str:
        return f"<Pseudonymizer tokens={len(self._reverse)} closed={self._closed}>"

    __str__ = __repr__

    def __getstate__(self):
        raise TypeError("Pseudonymizer 는 직렬화(pickle)할 수 없다")

    def __reduce__(self):
        raise TypeError("Pseudonymizer 는 직렬화·복사할 수 없다")

    def __reduce_ex__(self, protocol):
        raise TypeError("Pseudonymizer 는 직렬화·복사할 수 없다")

    def __copy__(self):
        raise TypeError("Pseudonymizer 는 복사할 수 없다")

    def __deepcopy__(self, memo):
        raise TypeError("Pseudonymizer 는 복사할 수 없다")

    # ----- 토큰 -----
    def token_for(self, kind: Kind, value: str) -> str:
        """value 를 가리는 토큰을 돌려준다(없으면 새로 만든다). 복원 불가 종류는 번호 없는 고정 토큰이다.

        대응표에 넣는 값이 토큰 모양이면 무력화해서 넣는다(복원 결과를 다시 복원하는 일을 막는다)."""
        if kind in _NEVER_STORE:
            return _NEVER_STORE_TOKEN[kind]
        if self._closed:
            raise RuntimeError("이미 닫힌 Pseudonymizer 다")
        if kind is Kind.PERSON:
            value = self._aliases.get(" ".join(value.split()), value)
        key = (kind, _norm_key(kind, value))
        token = self._forward.get(key)
        if token is None:
            number = self._counters.get(kind, 0) + 1
            self._counters[kind] = number
            token = f"[{_TOKEN_NAME[kind]}_{number}]"
            self._forward[key] = token
            self._reverse[token] = _neutralize(value)
            self._kind[token] = kind
        return token

    # ----- 가명화 -----
    def apply(
        self, text: str, policy: Policy, known_names: tuple[str, ...] | list[str] = ()
    ) -> MaskResult:
        """text 를 정책대로 처리한다.

        BLOCK 이고 점수가 policy.block_min_score 이상인 탐지가 하나라도 있으면 메시지 전체를 자리표시로 바꾼다(대응표는 건드리지
        않는다). BLOCK 인데 점수가 낮은 탐지는 값만 가린다(복원 불가 토큰)."""
        if self._closed:
            raise RuntimeError("이미 닫힌 Pseudonymizer 다")
        text = text or ""
        spans = detect(text, known_names)
        counts: dict[str, int] = {}
        blocked = False
        masked: list[Span] = []
        for s in spans:
            action = policy.action_for(s.kind)
            if action is Action.KEEP:
                continue
            counts[s.kind.value] = counts.get(s.kind.value, 0) + 1
            if action is Action.BLOCK and s.score >= policy.block_min_score:
                blocked = True
            else:  # MASK, 또는 점수가 낮아 강등된 BLOCK
                masked.append(s)
        if blocked:
            return MaskResult(BLOCKED_PLACEHOLDER, counts, True)
        out: list[str] = []
        pos = 0
        for s in masked:
            out.append(_neutralize(text[pos : s.start]))
            value = s.canonical or text[s.start : s.end]
            out.append(self.token_for(s.kind, value))
            pos = s.end
        out.append(_neutralize(text[pos:]))
        return MaskResult("".join(out), counts, False)

    # ----- 복원 -----
    def restore(
        self,
        text: str,
        kinds: frozenset[Kind] | None = None,
        generalize_unknown: bool = False,
    ) -> RestoreResult:
        """text 안의 토큰 중 이 요청이 만든 것만 원본으로 되돌린다.

        kinds 를 주면 그 종류의 토큰만 복원하고, 다른 종류의 토큰은 일반화 문구(``(연락처)`` 등)로 바꾼다(None 이면 전부 복원).
        이 요청이 만들지 않은 토큰 모양은 그대로 두고 unknown_tokens 에 적는다(generalize_unknown=True 면 ``(알 수 없는 항목)`` 으로 바꾼다).
        """
        restored: list[str] = []
        unknown: list[str] = []
        generalized: list[str] = []

        def sub(m: re.Match) -> str:
            raw = m.group(0)
            value = self._reverse.get(raw)
            if value is not None:
                kind = self._kind[raw]
                if kinds is None or kind in kinds:
                    restored.append(raw)
                    return value
                generalized.append(raw)
                return GENERIC_TEXT[kind]
            if raw in _FIXED_TOKENS or not _tokenish(raw):
                return raw
            unknown.append(raw)
            return UNKNOWN_TEXT if generalize_unknown else raw

        return RestoreResult(_BRACKETED.sub(sub, text or ""), restored, unknown, generalized)
