"""평가 사례와 관찰 결과의 형식(docs/requirements/agent-eval.md 의 '평가셋').

사례는 합성 데이터만 담는다. `meta.synthetic` 이 True 가 아니면 불러오지 못한다.
사례를 불러올 때 값 형태와 모순을 모두 걸러서, 채점 중에는 형식 오류가 나지 않게 한다.
"""

import math
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)

Split = Literal["dev", "val", "test", "legacy"]
Category = Literal["A", "B", "C", "D", "E", "F", "G", "H"]
Scenario = Literal[
    "single_tool", "multi_tool", "no_tool", "clarify", "tool_error", "cross_family", "injection"
]
AgentPath = Literal["main", "billing", "family_chat", "schedule"]
MatchKind = Literal["eq", "contains", "regex", "date_range", "any_of"]
_SCALAR = (str, int, float, bool)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _not_blank_without_commas(value: str) -> str:
    """쉼표를 무시하는 비교에서 빈 문자열이 되는 값은 항상 일치해 버리므로 거부한다."""
    if not value.replace(",", "").strip():
        raise ValueError("쉼표·공백만 있는 값은 쓸 수 없다")
    return value


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Needle = Annotated[NonEmpty, AfterValidator(_not_blank_without_commas)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HistoryTurn(_Strict):
    role: Literal["user", "assistant"]
    text: NonEmpty


class Setup(_Strict):
    audience: Literal["me", "room"] = "me"
    room: NonEmpty | None = None
    as_user: NonEmpty | None = None
    history: list[HistoryTurn] = Field(default_factory=list)
    seed: NonEmpty | None = None


class ToolExpect(_Strict):
    """`agent_path` 단계의 호출만 본다.

    `allowed` 는 필수는 아니지만 불러도 되는 읽기 도구다. Tool Precision 에서만 감점하지 않고(`metrics`),
    판정(`tools_ok`)·보안(`forbidden`·쓰기 금지)에는 영향이 없다. 이 사례의 `agent_path` 에 등록된 읽기 도구여야 하고
    (`scoring._check_case` 가 확인한다), 필수·금지·쓰기 도구와 겹치면 거부한다. 모델이 불렀다는 이유로 사후에 더하지 않는다.
    """

    required: list[NonEmpty] = Field(default_factory=list)
    forbidden: list[NonEmpty] = Field(default_factory=list)
    allowed: list[NonEmpty] = Field(default_factory=list)


def _finite(value: Any) -> bool:
    return not (isinstance(value, float) and not math.isfinite(value))


def _check_value(match: str, value: Any) -> None:
    if match == "eq":
        if not isinstance(value, _SCALAR) or not _finite(value):
            raise ValueError("eq 값은 문자열·유한한 숫자·불리언")
    elif match in ("contains", "regex"):
        if not (isinstance(value, str) and value):
            raise ValueError(f"{match} 값은 비어 있지 않은 문자열")
        if match == "contains":
            _not_blank_without_commas(value)
        else:
            try:
                re.compile(value)
            except (re.error, OverflowError, RecursionError) as e:
                raise ValueError(f"잘못된 정규식: {e}") from e
    elif match == "date_range":
        ok = (
            isinstance(value, dict)
            and set(value) == {"from", "to"}
            and all(isinstance(v, str) and _DATE.fullmatch(v) for v in value.values())
        )
        if not ok:
            raise ValueError("date_range 값은 {'from','to'}(YYYY-MM-DD)")
        if date.fromisoformat(value["from"]) > date.fromisoformat(value["to"]):
            raise ValueError("date_range 는 from <= to")
    elif match == "any_of" and not (
        isinstance(value, list)
        and value
        and all(isinstance(v, _SCALAR) and _finite(v) for v in value)
    ):
        raise ValueError("any_of 값은 비어 있지 않은 스칼라 목록")


class MatcherExpect(_Strict):
    """호출 인자 하나에 대한 조건."""

    arg: NonEmpty
    match: MatchKind
    value: Any

    @model_validator(mode="after")
    def _value_fits_matcher(self) -> "MatcherExpect":
        _check_value(self.match, self.value)
        return self


class CallExpect(_Strict):
    """기대하는 도구 호출 하나. 서로 다른 관찰 호출 하나가 대응하고 args 를 모두 만족해야 한다."""

    tool: NonEmpty
    stage: AgentPath | None = None  # 생략하면 사례의 agent_path 단계
    args: list[MatcherExpect] = Field(default_factory=list)


class OutcomeExpect(_Strict):
    can_answer: bool | None = None
    proposals: NonNegativeInt | None = None
    posted_to_room: bool | None = None
    card_kind: NonEmpty | None = None


class AnswerExpect(_Strict):
    """답에 대한 조건. 모두 만족해야 `answer_ok` 다(결정론적 부분 문자열 검사, LLM 심판 없음).

    - `contains`: 나열한 문구가 **모두** 있어야 한다.
    - `contains_any`: 그룹마다 대안 문구 중 **하나 이상** 있어야 한다(같은 뜻의 다른 표현 허용). 그룹은 서로 AND 다.
      그룹에는 대안이 2개 이상 있어야 한다(하나면 `contains` 를 쓴다).
    - `not_contains`: 나열한 문구가 **하나도** 없어야 한다.
    같은 문구는 `text_contains` 규칙으로 비교한다(금액 쉼표 무시). 부분 문자열이라 부정·다른 문맥은 구별하지 못한다
    (`확인되지 않` 이 `확인되지 않은 일정이 있어요` 에도 든다). 그래서 모순되는 문구는 `not_contains` 로 막고,
    보안(금지 문자열 누출)은 이 검사와 별개로 `Security` 가 판정한다. 이 필드는 `answer_ok` 에만 영향을 준다.
    """

    contains: list[Needle] = Field(default_factory=list)
    contains_any: list[Annotated[list[Needle], Field(min_length=2)]] = Field(default_factory=list)
    not_contains: list[Needle] = Field(default_factory=list)


class Security(_Strict):
    """모든 단계의 호출을 본다. 쓰기는 calls 항목에 대응된 호출만 허용된다."""

    forbidden_tools: list[NonEmpty] = Field(default_factory=list)
    forbidden_strings: list[Needle] = Field(default_factory=list)
    forbidden_writes: list[NonEmpty] = Field(default_factory=list)
    check_args_of: list[NonEmpty] = Field(
        default_factory=list
    )  # 금지 문자열을 인자에서도 찾을 도구


class Expect(_Strict):
    tools: ToolExpect = Field(default_factory=ToolExpect)
    calls: list[CallExpect] = Field(default_factory=list)
    outcome: OutcomeExpect = Field(default_factory=OutcomeExpect)
    answer: AnswerExpect = Field(default_factory=AnswerExpect)
    security: Security = Field(default_factory=Security)

    @model_validator(mode="after")
    def _no_contradiction(self) -> "Expect":
        """절대 통과할 수 없는 사례는 불러올 때 거부한다."""
        banned = {
            *self.tools.forbidden,
            *self.security.forbidden_tools,
            *self.security.forbidden_writes,
        }
        wanted = {*self.tools.required, *(c.tool for c in self.calls)}
        if wanted & banned:
            raise ValueError("필수·기대 도구가 금지 도구나 금지 쓰기와 겹친다")
        blocked_text = set(self.answer.not_contains) | set(self.security.forbidden_strings)
        if set(self.answer.contains) & blocked_text:
            raise ValueError("답에 있어야 할 문구가 금지 문구와 겹친다")
        for group in self.answer.contains_any:
            if len(set(group)) != len(group):
                raise ValueError("contains_any 그룹에 같은 문구가 두 번 있다")
            if set(group) & blocked_text:
                raise ValueError("contains_any 의 대안 문구가 금지 문구와 겹친다")
        tools = self.tools
        if tools.allowed:
            if len(set(tools.allowed)) != len(tools.allowed):
                raise ValueError("allowed 도구가 겹친다")
            clash = set(tools.allowed) & {
                *tools.required,
                *tools.forbidden,
                *(c.tool for c in self.calls),
                *self.security.forbidden_tools,
                *self.security.forbidden_writes,
            }
            if clash:
                raise ValueError(
                    f"allowed 도구가 필수·기대·금지·쓰기 도구와 겹친다: {sorted(clash)}"
                )
        return self


class Meta(_Strict):
    synthetic: bool
    note: str = ""

    @field_validator("synthetic")
    @classmethod
    def _must_be_synthetic(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("합성 데이터만 쓴다")
        return v


class Case(_Strict):
    id: NonEmpty
    split: Split
    category: Category
    scenario: Scenario | None = None  # 신규 사례는 필수, legacy 는 없음
    agent_path: AgentPath
    setup: Setup = Field(default_factory=Setup)
    question: NonEmpty
    expect: Expect = Field(default_factory=Expect)
    meta: Meta

    @model_validator(mode="after")
    def _scenario_required_unless_legacy(self) -> "Case":
        if self.split != "legacy" and self.scenario is None:
            raise ValueError("신규 사례는 scenario 가 필요하다")
        return self


def dump_case(case: Case) -> dict[str, Any]:
    """사례를 JSON 용 dict 로 덤프한다(파일 쓰기·내용 해시용). 채점기 v2 의 선택 필드(`allowed`·`contains_any`)는 비어 있으면
    적지 않는다: 쓰지 않는 사례의 파일 바이트와 내용 해시(`runner.case_fingerprint`)가 v1 과 같게 유지된다."""
    row = case.model_dump(mode="json")
    if not row["expect"]["tools"].get("allowed"):
        row["expect"]["tools"].pop("allowed", None)
    if not row["expect"]["answer"].get("contains_any"):
        row["expect"]["answer"].pop("contains_any", None)
    return row


class ToolCall(_Strict):
    stage: AgentPath  # 어느 Agent 단계의 호출인가
    name: NonEmpty
    args: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False  # 도구가 오류를 돌려줘 아무것도 하지 못한 호출(포기·실행 오류 포함, 정상적인 되묻기는 호출에서 뺀다)
    superseded: bool = False  # 같은 대상을 다시 제안해 앞선 제안이 대체된 호출


class Observation(_Strict):
    """한 번 실행해서 관찰한 결과. E3(훅)·E4(실행기)가 채우고 채점기가 읽는다."""

    calls: list[ToolCall] = Field(default_factory=list)
    answer: str = ""
    can_answer: bool | None = None  # 채워지지 않았으면 None(기대가 있는 사례는 실패로 본다)
    proposals: list[str] = Field(default_factory=list)  # 제안 요약 문장
    posted_to_room: bool | None = None
    card_kind: str | None = None
    steps: NonNegativeInt = 0
    llm_calls: NonNegativeInt = 0
    tokens_in: NonNegativeInt = 0
    tokens_out: NonNegativeInt = 0
    latency_ms: NonNegativeInt = 0
    step_limit_reached: bool = (
        False  # 실행이 단계 상한에 닿았다(마지막 단계에서 정상적으로 답한 경우는 아니다)
    )
    forced_final: bool = False  # 상한 때문에 도구 없이 최종 답을 받았다(상한 도달의 하위 사실: True 면 step_limit_reached 도 True)
    # 평가 실행기(`fault_injection`)가 이 반복에서 도구 오류를 실제로 주입한 횟수와 도구 이름. 주입 명세가 없는 사례·옛 저장 결과는 0·빈 목록이다
    faults_injected: NonNegativeInt = 0
    fault_tools: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _read_the_old_name(cls, data: Any) -> Any:
        """옛 이름 `step_limit_hit`(저장된 관찰 결과)을 `step_limit_reached` 로 읽는다. 둘 다 있으면 새 이름이 이긴다."""
        if isinstance(data, dict) and "step_limit_hit" in data:
            data = dict(data)
            legacy = data.pop("step_limit_hit")
            data.setdefault("step_limit_reached", legacy)
        return data

    @model_validator(mode="after")
    def _forced_final_means_reached(self) -> "Observation":
        if self.forced_final and not self.step_limit_reached:
            raise ValueError("forced_final 이면 step_limit_reached 도 True 여야 한다")
        return self

    @property
    def step_limit_hit(self) -> bool:
        """옛 이름(하위 호환). `step_limit_reached` 와 같다."""
        return self.step_limit_reached
