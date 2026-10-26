"""가족 채팅 AI 같은 호출부가 쓰는 통합 지점(순수 함수). DB 모델에 의존하지 않는다.

흐름: DB 에서 읽은 (id, 발화자 이름, 글자) 줄 -> ``prepare_transcript`` -> 가명화된 줄만 외부 LLM 으로 -> 응답 JSON ->
``restore_json`` 으로 이 요청이 만든 토큰만 복원. 대응표는 ``Prepared.pseudonymizer`` 안(요청 메모리)에만 있다.
호출이 끝나면 ``prep.close()`` (또는 ``with prep:``)로 지운다.

이 방식은 종단간 암호화(E2EE)가 아니다. 서버는 원문을 읽고, 외부로 나가는 글자에서 개인정보를 줄일 뿐이다.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .detectors import KINSHIP_TERMS
from .policy import Policy
from .pseudonymizer import Pseudonymizer
from .types import Kind


@dataclass(frozen=True)
class Row:
    """입력 한 줄. (id, speaker_name, text) 튜플을 그대로 넘겨도 된다."""

    id: int
    speaker_name: str
    text: str


@dataclass(frozen=True)
class PreparedLine:
    """외부로 보내도 되는 한 줄. speaker 는 토큰(speaker_tokens=False 면 원래 이름), text 는 가명화된 글자."""

    id: int
    speaker: str
    text: str
    blocked: bool = False


@dataclass
class Prepared:
    """prepare_transcript 결과. pseudonymizer 는 같은 요청에서 응답을 복원할 때 쓴다(밖으로 내보내지 않는다)."""

    lines: list[PreparedLine]
    blocked_ids: list[int]
    counts_by_kind: dict[str, int]
    pseudonymizer: Pseudonymizer = field(repr=False)
    policy: Policy

    @property
    def blocked_count(self) -> int:
        return len(self.blocked_ids)

    def close(self) -> None:
        self.pseudonymizer.clear()

    def __enter__(self) -> "Prepared":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


@dataclass(frozen=True)
class JsonRestoreResult:
    """복원 결과. generalized_tokens 는 정책의 restore_kinds 에 없어 일반화 문구로 바꾼 토큰이다."""

    value: Any
    restored_tokens: list[str]
    unknown_tokens: list[str]
    generalized_tokens: list[str] = field(default_factory=list)


def prepare_transcript(
    rows: Iterable[Row | Sequence],
    member_names: Iterable[str],
    policy: Policy,
    speaker_tokens: bool = True,
) -> Prepared:
    """줄마다 글자를 가명화한다. 발화자 이름도 PERSON 토큰으로 바꾼다(speaker_tokens=True).

    member_names 는 그 가족 구성원의 실제 이름·표시 이름이다. 발화자 이름도 이름 사전에 자동으로 더한다.
    BLOCK 대상이 있는 줄은 글자 전체가 자리표시로 바뀌고(id·순서는 유지) blocked_ids 에 들어간다.
    counts_by_kind 는 글자 속에서 찾은 개인정보 수다(발화자 토큰은 세지 않는다).
    """
    normalized = [r if isinstance(r, Row) else Row(*r) for r in rows]
    names = list(dict.fromkeys(" ".join(str(n).split()) for n in member_names if n))
    for r in normalized:
        speaker = " ".join((r.speaker_name or "").split())
        if speaker and speaker not in names:
            names.append(speaker)
    known = tuple(names)
    pz = Pseudonymizer()
    lines: list[PreparedLine] = []
    blocked_ids: list[int] = []
    counts: dict[str, int] = {}
    try:
        for r in normalized:
            speaker = " ".join((r.speaker_name or "").split())
            # 엄마·아빠 같은 가족 호칭이 표시 이름이면 그대로 둔다(본문의 '엄마' 와 모델이 이어서 이해할 수 있게)
            tokenize = speaker_tokens and speaker and speaker not in KINSHIP_TERMS
            token = pz.token_for(Kind.PERSON, speaker) if tokenize else speaker
            result = pz.apply(r.text, policy, known)
            for kind, n in result.counts_by_kind.items():
                counts[kind] = counts.get(kind, 0) + n
            if result.blocked:
                blocked_ids.append(r.id)
            lines.append(PreparedLine(r.id, token, result.text, result.blocked))
    except Exception:
        pz.clear()
        raise
    return Prepared(lines, blocked_ids, counts, pz, policy)


def restore_value(
    prep: Prepared, value: str, generalize_unknown: bool = False
) -> JsonRestoreResult:
    """문자열 하나를 복원한다. 정책의 restore_kinds 에 있는 종류만 원래 값으로 되돌리고 나머지는 일반화 문구로 바꾼다."""
    result = prep.pseudonymizer.restore(
        value, prep.policy.restore_kinds, generalize_unknown=generalize_unknown
    )
    return JsonRestoreResult(
        result.text, result.restored_tokens, result.unknown_tokens, result.generalized_tokens
    )


def restore_json(prep: Prepared, obj: Any, generalize_unknown: bool = False) -> JsonRestoreResult:
    """응답 JSON 의 문자열을 재귀로 복원한다(dict 의 값과 **키**, list·tuple·set 의 원소 모두).

    문자열이 아닌 값(숫자·불리언·None)은 그대로 둔다. 복원 범위는 prep.policy.restore_kinds 이고, 그 밖 종류의 토큰은 일반화
    문구로 바뀐다. unknown_tokens 에는 이 요청이 만들지 않은 토큰 모양이 모인다(generalize_unknown=True 면 그 자리도 일반화 문구).
    호출부는 이 함수를 응답 검증(clean_analysis 등)보다 먼저 불러야 이름 검증이 복원된 값으로 이뤄진다.
    """
    restored: list[str] = []
    unknown: list[str] = []
    generalized: list[str] = []

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            r = prep.pseudonymizer.restore(
                node, prep.policy.restore_kinds, generalize_unknown=generalize_unknown
            )
            restored.extend(r.restored_tokens)
            unknown.extend(r.unknown_tokens)
            generalized.extend(r.generalized_tokens)
            return r.text
        if isinstance(node, list):
            return [walk(x) for x in node]
        if isinstance(node, tuple):
            return tuple(walk(x) for x in node)
        if isinstance(node, (set, frozenset)):
            return type(node)(walk(x) for x in node)
        if isinstance(node, dict):
            return {walk(k): walk(v) for k, v in node.items()}
        return node

    return JsonRestoreResult(walk(obj), restored, unknown, generalized)
