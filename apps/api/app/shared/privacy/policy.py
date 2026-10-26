"""기능별 가명화 정책: 개인정보 종류마다 유지(KEEP) / 가리기(MASK) / 차단(BLOCK) 중 무엇을 할지 정한다.

정책은 데이터(딕셔너리)라서 값을 바꾸는 것만으로 동작이 달라진다.
- MASK : 그 값만 토큰(예: ``[PHONE_1]``)으로 바꿔 외부에 보낸다. 서버가 응답의 토큰을 복원한다.
- BLOCK: 그 **메시지 전체**를 외부로 보내지 않고 자리표시로 바꾼다(메시지 번호·순서는 유지, 개수만 센다).
- KEEP : 그대로 둔다.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from .types import Kind


class Action(StrEnum):
    KEEP = "KEEP"
    MASK = "MASK"
    BLOCK = "BLOCK"


# 차단된 메시지 자리에 들어가는 글자. 원문 일부도 담지 않는다.
BLOCKED_PLACEHOLDER = "[민감정보가 있어 제외된 메시지]"


@dataclass(frozen=True)
class Policy:
    """종류별 동작 표. 표에 없는 종류는 KEEP 이다."""

    name: str
    actions: dict[Kind, Action] = field(default_factory=dict)
    # 문맥을 얼마나 보낼지의 참고값(통합 쪽에서 쓴다). None 이면 호출하는 쪽 기본값을 따른다.
    max_context_lines: int | None = None
    # BLOCK 은 탐지 점수가 이 값 이상일 때만 메시지를 차단한다. 그보다 낮은 고위험 후보(문맥 없는 난수 모양 숫자 등)는
    # 값만 가리고(복원 불가 토큰) 메시지는 보낸다.
    block_min_score: float = 0.7
    # 응답에서 원래 값으로 되돌리는 종류. 나머지 종류의 토큰은 일반화 문구로 바꾼다(요약에 전화·이메일이 되살아나
    # AI 결과 캐시와 모든 구성원 화면에 들어가는 것을 막는다).
    restore_kinds: frozenset[Kind] = frozenset({Kind.PERSON, Kind.ADDRESS, Kind.PHONE, Kind.EMAIL})
    # 자유 글·JSON API(``prepare_json``)에서 숫자 값(금액 등)을 어떻게 할지: keep(그대로) / round(유효숫자 2자리로 뭉갬).
    # 가족 채팅 ``prepare_transcript`` 는 쓰지 않는다.
    number_mode: str = "keep"

    def __post_init__(self) -> None:
        if self.number_mode not in ("keep", "round"):
            raise ValueError("number_mode 는 keep 또는 round 다")

    def action_for(self, kind: Kind) -> Action:
        return self.actions.get(kind, Action.KEEP)


_STRICT_ACTIONS: dict[Kind, Action] = {
    Kind.PHONE: Action.MASK,
    Kind.EMAIL: Action.MASK,
    Kind.ADDRESS: Action.MASK,
    Kind.PERSON: Action.MASK,
    Kind.ACCOUNT: Action.BLOCK,
    Kind.SECRET: Action.BLOCK,
    Kind.RRN: Action.BLOCK,
    Kind.CARD: Action.BLOCK,
}

# 요약 + 일정 + 할 일을 한 번에 뽑는 대화 분석
# 복원: 담당자(PERSON) 연결과 일정 장소(ADDRESS)만
ANALYSIS = Policy(
    "analysis", dict(_STRICT_ACTIONS), restore_kinds=frozenset({Kind.PERSON, Kind.ADDRESS})
)
# 답장 추천: 같은 규칙에 문맥은 최소(최근 몇 줄만)
REPLY = Policy(
    "reply", dict(_STRICT_ACTIONS), max_context_lines=15, restore_kinds=frozenset({Kind.PERSON})
)
# 대화 주제 추천
TOPICS = Policy(
    "topics", dict(_STRICT_ACTIONS), max_context_lines=30, restore_kinds=frozenset({Kind.PERSON})
)

# AI 어시스턴트 질문·앞 대화·도구 결과(자유 글·JSON)용. 전부 가리되 고위험(점수 >= block_min_score)은 메시지 통째 제외가 아니라
# **그 값만** 고정 자리표시(``[RRN]`` 등)로 바꾼다(``prepare_text``/``prepare_json`` 은 항상 값 단위다). 복원은 이름·주소만이고
# 전화·이메일은 응답에서 ``(연락처)``·``(이메일)`` 이 된다. 숫자(금액)는 그대로 둔다.
ASSISTANT = Policy(
    "assistant", dict(_STRICT_ACTIONS), restore_kinds=frozenset({Kind.PERSON, Kind.ADDRESS})
)

POLICIES: dict[str, Policy] = {p.name: p for p in (ANALYSIS, REPLY, TOPICS, ASSISTANT)}
