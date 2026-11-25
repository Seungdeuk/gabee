"""실제 호출 전 사전 점검(E7a). `--preflight` 로 단독 실행하고, `--real` 은 시작 전에 같은 점검을 반드시 통과해야 한다.

이 점검은 실제 모델 호출도, 어떤 네트워크 전송도 하지 않는다. 앱이 모델에게 보내려던 요청은 **가짜 전송 함수**로 가로채 본다
(가짜 모델로 앱 경로를 한 번 끝까지 돌린다: `runner.run_cases(mode="fake")`. 실제 전송 함수가 불리면 `TripwireCalled` 로 즉시 멈춘다).
키·토큰·비밀번호 값은 어떤 출력에도 넣지 않는다("있음/없음"만, 길이도 적지 않는다). `.env` 를 직접 읽지 않고 `Settings` 로딩 결과만 본다.

점검 항목(번호는 출력 표와 같다): 1 API 키 유무·설정 로딩 / 2 모델·단가표·토큰·단계 설정 / 3 NER 필수 모드의 실제 로드·추론 /
4 최종 전송 본문의 개인정보 보호 경로(가짜 전송) / 5 합성 DB·운영 DB 차단 / 6 허용 호스트·네트워크 경계 / 7 실행 대상 사례 /
8 예상 호출 횟수·토큰·비용(보수적 최악 비용 포함) / 9 결과 저장 위치·Git 추적 제외.

## 보수적 최악 비용(항목 8)
`사례 수 x 반복 x 단계 상한 x call_cost(입력 토큰, max_tokens)`. 단계 상한은 메인 도구 루프의 `MAX_STEPS`(메인이 한 질문에서 모델을 부르는 최대 횟수),
출력은 Agent 경로의 설정 상한(`agent_max_output_tokens`)과 일반 상한(`anthropic_max_tokens`) 중 큰 값, 입력은 `--tokens-in` 과 가짜 전송으로 잰 본문 추정 중 큰 값이다.
승인 금액을 넘으면 거부한다. 하위 Agent(정산·소통·일정)가 도는 호출은 이 곱에 따로 더하지 않는다: 그 호출도 실행 중 `usage.meter_llm_calls` 가
호출 직전에 최악 비용을 검사해 막는다(사전 점검은 "시작해도 되는가"의 보수적 문턱이고 지출 상한 자체는 실행 중 검사다).
"""

import json
import os
import re
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import real_gate
from .adapter import LegacyCase
from .cost import PRICES, BudgetExceeded, Ledger, call_cost
from .real_gate import PreflightRecord
from .write_tools import WRITE_TOOLS

PASS, FAIL, WARN = "통과", "실패", "경고"
AUTH_FRAGMENTS = ("x-api-key", "authorization", "bearer ")  # 본문에 있으면 안 되는 인증 헤더 문자열
KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")
HIGH_KINDS = (
    "PHONE",
    "EMAIL",
    "RRN",
    "CARD",
    "ACCOUNT",
    "SECRET",
)  # 본문에서 탐지되면 실패인 개인정보 종류
# Agent 경로(메인·소통·일정·정산 Agent 와 대화 분석)가 쓸 수 있는 출력 상한의 허용 천장. 앱의 `settings.agent_max_output_tokens` 기본값과 같은 값을
# 여기에 고정해 두고(시험이 둘이 같은지 본다), 환경변수로 이보다 크게 올리면 본문 점검이 실패하도록 한다(앱 값을 읽어 오면 상한이 몰래 커진다).
# 천장보다 낮춘 설정은 통과한다. 확인된 Agent 호출(`agent_path_of`) 밖의 호출(답 검증, 미분류 일반 호출)은 이 천장이 아니라 일반 상한(`anthropic_max_tokens`)으로 본다.
# 천장은 상수라 일반 상한 설정(ANTHROPIC_MAX_TOKENS)을 바꿔도 올라가지 않는다.
AGENT_OUTPUT_CEILING = 10000
ANALYSIS_TOOL = "analyze_recent_chat"
DETECT_CHUNK_CHARS = 3000  # 본문 탐지는 이 크기로 잘라 넣는다(NER 입력 상한 8000자보다 훨씬 작게). 경계에 걸친 값은 놓칠 수 있다(문서에 적는다)
NER_PROBE_TEXT = (
    "지민이는 어제 수진이한테 전화해서 내일 병원 같이 가자고 했어요. 지민 번호는 {phone}예요."
)


# 합성 PERSON(가족 이름) 발신 기록 라벨. 정책: 합성 PERSON 의 외부 전송은 실제 개인정보 유출과 같게 집계하지 않는다(실패 조건 아님).
# 가명화 대상 경로에서 원문이 남으면 "가명화 정책 미준수"로 별도 기록한다. 이 PR 은 앱의 가명화 동작을 바꾸지 않는다.
PERSON_EXEMPT = "의도된 예외(ADR 0014: 메인 채팅은 가명화를 걷어냄)"
PERSON_MISS = "가명화 정책 미준수(기록)"
PERSON_GAP = "알려진 갭(정산 가명화 미구현, 문서 기록)"
PERSON_NONE = "원문 없음"
PERSON_UNKNOWN = "경로 미확인(기록)"


def classify_person(stage: str, count: int) -> str:
    """호출 경로(stage)와 합성 PERSON 원문 건수로 분류 라벨을 정한다."""
    if count == 0:
        return PERSON_NONE
    return {
        "main": PERSON_EXEMPT,
        "billing": PERSON_GAP,
        "family_chat": PERSON_MISS,
        "schedule": PERSON_MISS,
    }.get(stage, PERSON_UNKNOWN)


class _Bodies(list):
    """가로챈 본문 목록(list)에 PERSON 발신 기록(`person_rows`: (사례, 경로, 원문 건수, 라벨))을 붙인 것."""

    person_rows: tuple[tuple[str, str, int, str], ...] = ()


def _is_analysis_body(body: Mapping[str, Any]) -> bool:
    """대화 분석 호출의 본문인가: 구조화 출력(`output_config`)이면서 시스템 프롬프트가 분석용 프롬프트와 정확히 같다.
    일정 Agent 의 구조화 출력·메인·정산·소통 호출은 해당하지 않는다."""
    from app.features.family_chat.ai_service import ANALYSIS_SYSTEM

    return "output_config" in body and body.get("system") == ANALYSIS_SYSTEM


# 정산·소통 Agent 시스템 프롬프트의 고정 머리말(정산은 뒤에 사용자 이름이 붙는다). 시험이 실제 프롬프트가 이 머리말로 시작하는지 본다.
BILLING_SYSTEM_PREFIX = "당신은 가족 비서 '가비'의 가계(정산) 담당 에이전트입니다."
FAMILY_CHAT_SYSTEM_PREFIX = "당신은 가족 비서 '가비'의 가족 채팅 담당 에이전트입니다."
AGENT_PATHS = ("main", "family_chat", "billing", "schedule", "analysis")


def agent_path_of(body: Mapping[str, Any]) -> str | None:
    """확인된 여섯 호출(메인·메인 웹 검색 = main, 소통 = family_chat, 정산 = billing, 일정 = schedule, 대화 분석 = analysis) 중 어느 것인지 **명시적으로** 가린다.

    구조화 출력(`output_config`)은 시스템 프롬프트가 분석용·일정용과 정확히 같을 때만, 나머지는 시스템 프롬프트의 고정 머리말로 가린다.
    그 밖의 모든 본문(답 검증, 앞으로 평가 경로에 생길 일반 호출, 알 수 없는 본문)은 None: Agent 천장을 받지 못하고 일반 상한으로 본다."""
    from app.features.ai_assistant.knowledge import rag_chat
    from app.features.family_chat.ai_service import ANALYSIS_SYSTEM
    from app.features.schedule.agent import prompts as schedule_prompts

    system = body.get("system")
    if not isinstance(system, str):
        return None
    if "output_config" in body:
        if system == ANALYSIS_SYSTEM:
            return "analysis"
        return "schedule" if system == schedule_prompts.CHAT_SYSTEM else None
    if system.startswith(BILLING_SYSTEM_PREFIX):
        return "billing"
    if system.startswith(FAMILY_CHAT_SYSTEM_PREFIX):
        return "family_chat"
    return "main" if system.startswith(rag_chat.SYSTEM_PROMPT) else None


def _is_agent_body(body: Mapping[str, Any]) -> bool:
    """확인된 Agent 호출 경로의 본문인가(`agent_path_of`). 답 검증 등 나머지는 아니다."""
    return agent_path_of(body) is not None


def max_tokens_cap(body: Mapping[str, Any], default: int) -> int:
    """이 본문이 넘으면 안 되는 `max_tokens`. 확인된 Agent 호출만 고정 천장 `AGENT_OUTPUT_CEILING`(일반 상한 설정과 무관하게 그대로),
    나머지는 `default`(설정의 `anthropic_max_tokens`)."""
    return AGENT_OUTPUT_CEILING if _is_agent_body(body) else default


def agent_output_cap() -> int:
    """비용 계산에 쓰는 Agent 경로의 실제 출력 상한(설정값). 천장을 넘으면 본문 점검이 따로 실패시킨다."""
    from app.shared.config import settings

    return settings.agent_max_output_tokens


def _person_names() -> tuple[str, ...]:
    from .seeds import data as seed_data
    from .seeds import data_w2

    # 모든 월드의 합성 이름(구성원 이름은 같고 가족 이름만 다르다). 다른 월드의 가족 이름은 그 월드 본문에 나오지 않으므로 개발셋의 건수는 그대로다
    names = seed_data.FICTIONAL_NAMES | data_w2.FICTIONAL_NAMES
    return tuple(sorted((n for n in names if len(n) >= 2), key=len, reverse=True))


CONTEXT_CHARS = 12  # 고위험 탐지 실패 메시지에 넣는 '앞 글 종류' 요약의 최대 길이(글자 수)


def _char_class(ch: str) -> str:
    if ch == "#":
        return "#"  # 가려진 고위험 구간
    if ch.isdigit():
        return "9"
    if ch.isspace():
        return "_"
    if "a" <= ch.lower() <= "z" and ch.isascii():
        return "a"
    if "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㅣ":
        return "가"
    return "."


def _context_summary(chunk: str, start: int, high_spans: list[tuple[int, int]]) -> str:
    """값 바로 앞 글을 **글자 종류로만** 요약한다(원문을 넣지 않는다). 같은 글의 고위험 구간을 모두 먼저 `#` 로 가린 뒤 숫자 9·영문 a·한글 가·공백 _·기호 .
    으로 바꾼다(길이는 `CONTEXT_CHARS` 이하). 인접한 다른 고위험 값의 끝자리 숫자 등이 진단 정보로 새지 않게 하려는 것이다."""
    masked = list(chunk)
    for a, b in high_spans:
        masked[a:b] = "#" * (b - a)
    return "".join(_char_class(ch) for ch in masked[max(0, start - CONTEXT_CHARS) : start])


class TripwireCalled(AssertionError):
    """점검 중 실제 전송 함수가 불렸다(일어나면 안 된다)."""


@dataclass(frozen=True)
class Check:
    no: int
    name: str
    status: str  # 통과 | 실패 | 경고
    detail: str


@dataclass(frozen=True)
class PreflightInput:
    split: str
    run_id: str
    approve: Decimal
    model: str
    repeat: int
    requested_ids: tuple[str, ...]
    items: list  # 로더가 고른 사례(LegacyCase | Case), 사례 파일 순서
    missing_ids: tuple[str, ...]
    calls_per_case: int
    tokens_in: int
    tokens_out: int
    results_root: Path
    default_results: Path
    ledger: Ledger
    scripts: Mapping[str, Any] = field(default_factory=dict)  # 가짜 점검 실행용 사례별 대본(dev)
    stage: str = "other"
    source_file: Any = (
        None  # dev 사례 파일 경로(--dev-file). 일반화 사례는 허용된 파일에서만 인정한다(7번)
    )
    require_env: bool = False  # --real 은 허가용 환경변수가 필수. --preflight 는 없어도 점검을 돌린다(그 항목만 '실호출 시 필요')


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)
    record: PreflightRecord | None = None
    worst_case: Decimal | None = None
    person_rows: tuple[tuple[str, str, int, str], ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c.status != FAIL for c in self.checks)

    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def lines(self) -> list[str]:
        out = ["[사전 점검] 실제 모델 호출·네트워크 전송 없음(가짜 전송 함수로만 점검)"]
        for c in self.checks:
            first, *rest = c.detail.split("\n")
            out.append(f" {c.no}. [{c.status}] {c.name}: {first}")
            out += [f"        {line}" for line in rest]
        out.append(
            f"  사전 점검 결과: {'모두 통과' if self.ok else '실패가 있다 - 실제 호출을 시작하지 않는다'}"
        )
        return out


# ---------- 개별 점검 ----------
def _check_key(require_env: bool = False) -> Check:
    from app.shared.config import settings

    name = "API 키·설정 로딩·허가 환경변수"
    if not settings.anthropic_api_key:
        return Check(1, name, FAIL, "서버 설정에 ANTHROPIC_API_KEY 가 없어 실제 모델을 쓸 수 없다")
    base = "ANTHROPIC_API_KEY 있음(값은 출력하지 않는다), 설정 로딩 성공"
    if real_gate.env_allows():
        return Check(1, name, PASS, f"{base}, 환경변수 {real_gate.ENV_NAME} 설정됨")
    if require_env:
        return Check(
            1, name, FAIL, f"{base}, 환경변수 {real_gate.ENV_NAME}=1 이 없다(--real 에 필수)"
        )
    return Check(
        1,
        name,
        WARN,
        f"{base}, 환경변수 {real_gate.ENV_NAME}=1 은 아직 없다(실호출 시 필요, 이 점검은 실호출이 아니라 계속한다)",
    )


def _max_steps() -> int:
    from app.features.ai_assistant.knowledge import rag_chat

    return int(rag_chat.MAX_STEPS)


def _check_model(model: str) -> Check:
    from app.shared.config import settings

    name = "모델명·API 설정 일치"
    if settings.llm_model != model:
        return Check(
            2,
            name,
            FAIL,
            f"모델은 서버 설정(ANTHROPIC_MODEL)으로 고른다. 설정은 {settings.llm_model}, 요청은 {model}",
        )
    if model not in PRICES:
        return Check(
            2, name, FAIL, f"단가표에 없는 모델: {model}(단가를 모르는 모델은 추정하지 않는다)"
        )
    return Check(
        2,
        name,
        PASS,
        f"모델 {model}(설정과 같음, 단가표 있음), anthropic_max_tokens={settings.anthropic_max_tokens}, agent_max_output_tokens={settings.agent_max_output_tokens}, 메인 단계 상한 MAX_STEPS={_max_steps()}",
    )


def ner_probe() -> tuple[bool, str]:
    """NER 필수 모드의 실제 초기화·추론(합성 문장). 돌려주는 것: (통과 여부, 근거). 외부 전송 없음."""
    from app.shared.privacy import ner
    from app.shared.privacy.ner import detect_with_ner

    from .seeds import data as seed_data

    mode = ner.current_mode()
    if mode != "required":
        return (
            False,
            f"PRIVACY_NER_MODE 가 required 가 아니다(현재 {mode}): 실제 호출은 NER 필수 모드에서만 한다",
        )
    started = time.perf_counter()
    try:
        ner.reset()  # 캐시된 상태가 아니라 실제 모델 폴더에서 새로 불러 본다
        ner.ensure_ready()
        text = NER_PROBE_TEXT.format(phone=seed_data.PHONE_AB)
        spans = ner.spans_for(text)
        found = detect_with_ner(text)
    except Exception as e:  # noqa: BLE001  로드·추론 실패는 종류만 적는다(모델 경로·내용 미출력)
        return False, f"NER 로드·추론 실패({type(e).__name__}): 필수 모드이므로 호출하지 않는다"
    elapsed = int((time.perf_counter() - started) * 1000)
    kinds: dict[str, int] = {}
    for s in found:
        kinds[str(s.kind.value)] = kinds.get(str(s.kind.value), 0) + 1
    shown = " ".join(f"{k}x{v}" for k, v in sorted(kinds.items())) or "없음"
    if not spans:
        return False, f"NER 이 합성 문장에서 아무것도 찾지 못했다(모델이 일하지 않음, {elapsed}ms)"
    if "PHONE" not in kinds or "PERSON" not in kinds:
        return False, f"기대한 종류(PERSON·PHONE)를 다 찾지 못했다: 탐지 {shown} ({elapsed}ms)"
    return (
        True,
        f"NER 로드·추론 성공({elapsed}ms), NER 구간 {len(spans)}개, 합성 문장 탐지 종류 {shown}",
    )


def _check_ner() -> Check:
    ok, detail = ner_probe()
    return Check(3, "NER 필수 모드 초기화·추론", PASS if ok else FAIL, detail)


def _texts_of(body: Mapping[str, Any]) -> str:
    """요청 본문에서 모델이 읽는 글(시스템·메시지·도구 결과)을 하나로 모은다. 도구 명세(정적 설명)는 뺀다."""
    parts: list[str] = [str(body.get("system") or "")]

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            for k, v in value.items():
                if k not in ("type", "id", "tool_use_id"):
                    walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    walk(body.get("messages") or [])
    return "\n".join(p for p in parts if p)


def _chunks(text: str, size: int = DETECT_CHUNK_CHARS) -> list[str]:
    """탐지기에 넣을 크기로 줄 단위로 자른다(NER 은 글 하나의 길이·창 수 상한이 있고 넘으면 필수 모드에서 실패한다). 한 줄이 크면 그 줄을 자른다."""
    out: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > size:
            if current:
                out.append(current)
                current = ""
            out.append(line[:size])
            line = line[size:]
        if len(current) + len(line) + 1 > size and current:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def _needles_of(item: Any, relax: bool = False) -> tuple[list[str], int]:
    """그 사례의 비공개 문자열과 제외한 개수. 질문·이전 대화에 이미 있는 글은 본문에 있어도 노출이 아니라서 뺀다.

    `relax` 는 정산 경로 사례에서 정산 도구가 성공했을 때(`runner.expense_titles_visible`)만 켠다: 가족이 모두 보는 지출 제목은 정산 도구 결과로 본문에 들어가는 것이 정상이다."""
    from . import runner

    case = runner._case_of(item)
    needles = (
        list(runner.LEGACY_FORBIDDEN_STRINGS)
        if isinstance(item, LegacyCase)
        else runner._viewer_strings(case, relax)
    )
    given = case.question + "\n" + "\n".join(h.text for h in case.setup.history)
    kept = [n for n in needles if n and n not in given]
    return kept, len(needles) - len(kept)


def _person_lines(rows: tuple[tuple[str, str, int, str], ...]) -> str:
    """합성 PERSON 원문 발신 기록 표(사례별·경로별 건수와 분류). 실패 조건이 아니라 기록이다."""
    if not rows:
        return ""
    miss = sum(n for _, _, n, label in rows if label == PERSON_MISS)
    head = f"\nPERSON 원문 발신 기록(실패 아님, 합성 이름 기준) - {PERSON_MISS} {miss}건"
    return head + "".join(
        f"\n  {cid} | {stage} | 원문 {n}건 | {label}" for cid, stage, n, label in rows
    )


def _fake_pass(inp: PreflightInput) -> tuple[Check, list[dict], int]:
    """가짜 전송 함수로 앱 경로를 끝까지 돌리고 본문을 가로채 점검한다. 돌려주는 것: (점검, 본문 목록, 최대 추정 입력 토큰)."""
    from app.shared.config import settings
    from app.shared.llm import transport
    from app.shared.privacy.ner import detect_with_ner

    from . import fake_model, runner, usage
    from .cost import Scope

    name = "최종 LLM 전송 본문의 개인정보 보호 경로"
    real_key = settings.anthropic_api_key  # 값은 출력하지 않고 본문에 없는지만 본다
    calls: list[int] = []
    original = transport.post_messages

    def tripwire(*a: Any, **k: Any) -> dict:
        calls.append(1)
        raise TripwireCalled("실제 전송 함수가 불렸다")

    # 가짜 전송 점검은 항상 가짜 모드다. 검증 분할은 목적을 밝혀야 돌고(`runner._resolve`) 점검은 실행이 아니므로 중립 목적(baseline)을 쓴다: 실호출 허가와 무관하다
    purpose = "baseline" if inp.split == "val" else None
    options = runner.RunOptions(f"{inp.run_id}-preflight", mode="fake", purpose=purpose)
    ledger = Ledger((Scope.RUN,))
    transport.post_messages = tripwire
    fake_model.FakeModel.record_bodies = True
    try:
        report = runner.run_cases(inp.items, options, scripts=dict(inp.scripts), ledger=ledger)
    except Exception as e:  # noqa: BLE001
        return Check(4, name, FAIL, f"가짜 전송 점검 실행이 실패했다({type(e).__name__})"), [], 0
    finally:
        fake_model.FakeModel.record_bodies = False
        transport.post_messages = original
    if calls:
        return Check(4, name, FAIL, "점검 중 실제 전송 함수가 불렸다(일어나면 안 된다)"), [], 0
    bad_status = [r.case_id for r in report.records if r.status != "judged"]
    if bad_status:
        return (
            Check(
                4,
                name,
                FAIL,
                f"점검용 가짜 실행이 끝나지 않은 사례가 있다: {sorted(set(bad_status))}",
            ),
            [],
            0,
        )
    problems: list[str] = []
    bodies = _Bodies()
    skipped = 0
    max_in = 0
    kinds_seen: dict[str, int] = {}
    seen_person = 0
    names = _person_names()
    person: dict[tuple[str, str], int] = {}
    for item in inp.items:
        case = runner._case_of(item)
        skipped += _needles_of(item)[1]
        for (cid, repeat), fake in report.fakes.items():
            if cid != case.id:
                continue
            obs = getattr(report, "observations", {}).get((cid, repeat))
            needles, _ = _needles_of(item, runner.expense_titles_visible(case, obs))
            stages = (
                list(getattr(fake, "agents", ()))
                if len(getattr(fake, "agents", ())) == len(fake.bodies)
                else ["unknown"] * len(fake.bodies)
            )
            for stage, body in zip(stages, fake.bodies, strict=True):
                bodies.append(body)
                text = _texts_of(body)
                person[(case.id, stage)] = person.get((case.id, stage), 0) + sum(
                    text.count(n) for n in names
                )
                dump = json.dumps(body, ensure_ascii=False).lower()
                if any(f in dump for f in AUTH_FRAGMENTS) or KEY_PATTERN.search(dump):
                    problems.append(f"{case.id}: 본문에 키·인증 헤더 문자열이 있다")
                if real_key and len(real_key) >= 8 and real_key.lower() in dump:
                    problems.append(f"{case.id}: 본문에 API 키 값이 있다")
                if runner.FAKE_KEY in dump:
                    problems.append(f"{case.id}: 본문에 키 자리 값이 있다")
                if body.get("model") != settings.llm_model:
                    problems.append(f"{case.id}: 본문 model 이 설정과 다르다")
                mt = body.get("max_tokens")
                cap = max_tokens_cap(body, settings.anthropic_max_tokens)
                if not isinstance(mt, int) or isinstance(mt, bool) or mt > cap:
                    problems.append(f"{case.id}: max_tokens 가 없거나 상한({cap})보다 크다")
                hit = [n for n in needles if n in text]
                if hit:
                    problems.append(f"{case.id}: 비공개 문자열 {len(hit)}건이 본문에 그대로 있다")
                try:
                    spans = [
                        (chunk, sp) for chunk in _chunks(text) for sp in detect_with_ner(chunk)
                    ]
                except Exception as e:  # noqa: BLE001  탐지기를 못 쓰면 본문을 검증할 수 없다
                    problems.append(f"{case.id}: 개인정보 탐지기를 쓸 수 없다({type(e).__name__})")
                    spans = []
                for chunk, span in spans:
                    kind = str(span.kind.value)
                    kinds_seen[kind] = kinds_seen.get(kind, 0) + 1
                    if kind in HIGH_KINDS:
                        # 원인 추적용 진단: 경로·탐지 규칙·점수·값 길이·종류와 앞 글의 글자 종류 요약만 남긴다(원문 앞뒤 글·값·값 일부는 적지 않는다)
                        marks = [
                            (s.start, s.end)
                            for c, s in spans
                            if c is chunk and str(s.kind.value) in HIGH_KINDS
                        ]
                        summary = _context_summary(chunk, span.start, marks)
                        problems.append(
                            f"{case.id}: 본문({stage})에서 {kind}({span.source}, 점수 {span.score:.2f}, 길이 {span.end - span.start}) 로 탐지된 값이 있다(앞 글 종류: {summary})"
                        )
                    elif kind == "PERSON":
                        seen_person += 1
                max_in = max(max_in, usage.estimate_input_tokens(body))
    bodies.person_rows = tuple(
        (cid, stage, n, classify_person(stage, n)) for (cid, stage), n in sorted(person.items())
    )
    if not bodies:
        problems.append("가로챈 요청 본문이 없다(점검할 호출이 없었다)")
    if problems:
        uniq = list(dict.fromkeys(problems))
        return (
            Check(
                4,
                name,
                FAIL,
                "; ".join(uniq[:6]) + (f" 외 {len(uniq) - 6}건" if len(uniq) > 6 else ""),
            ),
            bodies,
            max_in,
        )
    shown = " ".join(f"{k}x{v}" for k, v in sorted(kinds_seen.items())) or "없음"
    return (
        Check(
            4,
            name,
            PASS,
            f"가짜 전송으로 사례 {len(inp.items)}건·본문 {len(bodies)}개 점검(실제 전송 0회): 키·인증 헤더 문자열 없음, model·max_tokens 일치, "
            f"비공개 문자열 0건(질문에 이미 있는 글 {skipped}건 제외), 고위험 탐지 0건(탐지 종류 {shown}), 추정 입력 토큰 최대 {max_in}. "
            "한계: 가짜 대본이 정한 경로의 본문만 본다(실제 모델이 다른 도구·인자를 고르면 달라진다), 개인정보 탐지는 이 환경의 NER 설정을 따르고(NER 은 3번이 따로 확인), 첫 실호출에서 실제 본문 길이·model·max_tokens 를 usage 로 확인한다"
            + _person_lines(bodies.person_rows),
        ),
        bodies,
        max_in,
    )


def _check_boundary() -> Check:
    from app.shared.config import settings

    from . import env

    name = "합성 DB·운영 DB 차단"
    try:
        env.check_process_boundary(Path(settings.data_dir))
    except Exception as e:  # noqa: BLE001  주소·경로를 적지 않는다(운영 DB 주소일 수 있다)
        return Check(5, name, FAIL, f"허용하지 않은 환경({type(e).__name__}): {str(e)[:120]}")
    return Check(
        5,
        name,
        PASS,
        "임시 폴더 아래의 SQLite 파일과 데이터 폴더만 쓴다(운영·공용 DB 주소는 거부한다)",
    )


def _check_network() -> Check:
    from . import network

    name = "허용 외부 호스트·네트워크 경계"
    problems: list[str] = []
    if real_gate.real_grant() is not None:
        problems.append("사전 점검 중에는 실제 호출 허가가 열려 있으면 안 된다")
    if real_gate.REAL_HOSTS != ("api.anthropic.com",):
        problems.append(f"허용 호스트가 api.anthropic.com 하나가 아니다: {real_gate.REAL_HOSTS}")
    try:
        with network.block_network(real_gate.REAL_HOSTS):
            problems.append("허가 없이 실제 모델 호스트가 열렸다")
    except real_gate.RealGateRefused:
        pass
    except Exception as e:  # noqa: BLE001
        problems.append(f"허가 없는 호스트 열기 점검이 예상 밖으로 끝났다({type(e).__name__})")
    outcome: dict[str, str] = {}
    try:
        with network.block_network(()):
            for label, action in (
                ("이름 조회", lambda: socket.getaddrinfo("preflight-probe.invalid", 443)),
                ("외부 연결", _probe_connect),
            ):
                try:
                    action()
                    outcome[label] = "열림"
                except network.NetworkBlocked:
                    outcome[label] = "막힘"
                except OSError:
                    outcome[label] = "막히지 않음"
    except Exception as e:  # noqa: BLE001
        problems.append(f"네트워크 차단 점검이 실패했다({type(e).__name__})")
    if outcome and set(outcome.values()) != {"막힘"}:
        problems.append(f"외부 연결이 막히지 않았다: {outcome}")
    proxies = sorted(
        {n.lower() for n in network.PROXY_ENV if os.environ.get(n)}
    )  # 이름만(값은 자격 증명일 수 있다)
    if problems:
        return Check(6, name, FAIL, "; ".join(problems))
    note = (
        f"프록시 변수 설정됨({', '.join(proxies)}; 값 미출력, 차단 구간에서는 비운다)"
        if proxies
        else "프록시 변수 없음"
    )
    return Check(
        6,
        name,
        WARN if proxies else PASS,
        f"허가가 열릴 때 허용 호스트는 {real_gate.REAL_HOSTS[0]} 하나뿐, 허가 없이는 열 수 없다. 차단 중 이름 조회·외부 연결 모두 막힘, "
        f"루프백은 이 프로세스가 연 포트만. {note}",
    )


def _probe_connect() -> None:
    s = socket.socket()
    try:
        s.settimeout(0.2)
        s.connect(("192.0.2.1", 443))  # RFC 5737 TEST-NET: 차단이 깨져도 실제 서비스에 닿지 않는다
    finally:
        s.close()


def _writes_in(item: Any) -> list[str]:
    from . import runner

    case = runner._case_of(item)
    named = {*case.expect.tools.required, *(c.tool for c in case.expect.calls)}
    writes = {t for names in WRITE_TOOLS.values() for t in names}
    return sorted(named & writes)


def reject_reason(item: Any, split: str) -> str | None:
    """실호출 대상에서 뺄 이유(없으면 None). 쓰기 도구를 기대한 사례·일정 쓰기 이름이 든 사례·seed 가 있는 사례는 뺀다."""
    from . import runner

    case = runner._case_of(item)
    if case.split != split:
        return f"분할 불일치({case.split} != {split})"
    reason = runner.unsupported_reason(item, runner.RunOptions("preflight", mode="real"), {})
    if reason:
        return reason
    writes = _writes_in(item)
    if writes:
        return f"쓰기 도구를 기대하는 사례다({', '.join(writes)}): 쓰기 평가 사례는 실호출 대상에서 제외한다"
    return None


def _check_cases(inp: PreflightInput) -> Check:
    from . import runner

    name = "실행 대상 사례 id·선택 결과"
    rows: list[str] = []
    problems: list[str] = []
    if inp.missing_ids:
        problems.append(f"존재하지 않는 사례 id: {list(inp.missing_ids)}")
    found = {runner._case_of(i).id for i in inp.items}
    if set(inp.requested_ids) - set(inp.missing_ids) != found:
        problems.append("요청한 id 와 로더가 고른 사례가 다르다")
    try:  # 사례가 커밋된(HEAD) 개발 사례와 같은지: 위장·수정·미커밋은 실호출 대상이 아니다
        runner.verify_committed(inp.items, inp.split)
        if inp.split == "dev":
            runner.verify_dev_source(inp.source_file, inp.items)
    except runner.RunnerRefused as e:
        problems.append(str(e))
    for item in inp.items:
        case = runner._case_of(item)
        why = reject_reason(item, inp.split)
        if why:
            problems.append(f"{case.id}: {why}")
        rows.append(
            f"{case.id} | 분류 {case.scenario or case.category} | 경로 {case.agent_path} | 읽기 전용 {'아니오' if why else '예'}"
            + (f" | 제외 사유: {why}" if why else "")
        )
    head = f"요청 {len(inp.requested_ids)}건, 선택 {len(inp.items)}건"
    if problems:
        return Check(
            7, name, FAIL, head + "\n" + "\n".join(rows + [f"문제: {p}" for p in problems])
        )
    return Check(7, name, PASS, head + ", 모두 읽기 전용·실호출 가능\n" + "\n".join(rows))


def sub_agent_steps() -> int:
    """하위 Agent 도구 루프의 호출 상한: `agent.run_agent` 의 `max_steps` 기본값(정산·소통 Agent 가 쓴다)."""
    import inspect

    from app.shared.llm import agent

    return int(inspect.signature(agent.run_agent).parameters["max_steps"].default)


def _calls_per_ask(tool: str, sub: int) -> int:
    """메인이 `ask_*` 도구 하나를 한 번 부를 때 하위 Agent 가 모델을 부르는 최대 횟수(코드에서 읽은 구조):
    정산(`ask_billing`)은 `run_agent` 루프 `sub` 회, 소통(`ask_family_chat`)은 같은 루프에 단계마다 대화 분석(`complete_json`) 1회가 더해질 수 있어 `2*sub` 회,
    일정(`ask_schedule`)은 `schedule/agent/chat.py` 의 구조화 출력 1회."""
    return {"ask_billing": sub, "ask_family_chat": 2 * sub, "ask_schedule": 1}.get(tool, sub)


def structural_max_calls() -> int:
    """질문 하나가 모델을 부르는 **구조적 이론 최대**(정보용, 사전 거부 기준이 아니다).

    = 메인 단계 상한(`rag_chat.MAX_STEPS`) + 답 검증 1회(`verify`) + (도구를 쓸 수 있는 메인 단계 수 MAX_STEPS-1) x (메인이 `ask_*` 를 한 단계에 하나씩 모두 부를 때
    하위 Agent 호출 합). 같은 `ask_*` 를 한 단계에 여러 번 부르는 경우와 하위 Agent 의 도구 안 호출은 더 있을 수 있다(이 값도 증명된 상한은 아니다)."""
    from app.features.ai_assistant.knowledge import rag_chat

    from .write_tools import READ_TOOLS

    sub = sub_agent_steps()
    asks = [t for t in sorted(READ_TOOLS["main"]) if t.startswith("ask_")]
    per_round = sum(_calls_per_ask(t, sub) for t in asks)
    return int(rag_chat.MAX_STEPS) + 1 + (int(rag_chat.MAX_STEPS) - 1) * per_round


def main_loop_worst(
    model: str, cases: int, repeats: int, tokens_in: int, max_tokens: int
) -> Decimal:
    """메인 루프 기준 최악 상한(하위 Agent 호출 포함 안 함): 사례 x 반복 x (메인 단계 상한 + 답 검증 1) x call_cost(입력, max_tokens). 사전 거부 기준이다."""
    return cases * repeats * (_max_steps() + 1) * call_cost(model, tokens_in, max_tokens)


def structural_worst_case(
    model: str, cases: int, repeats: int, tokens_in: int, max_tokens: int
) -> Decimal:
    """구조적 이론 최대 호출 수 기준 비용(정보용, 거부하지 않는다)."""
    return cases * repeats * structural_max_calls() * call_cost(model, tokens_in, max_tokens)


def expected_analysis_calls(items: Any) -> int:
    """대상 사례가 기대하는 대화 분석 호출(`analyze_recent_chat`) 수의 합(기대 호출 목록에서 센다)."""
    from . import runner

    return sum(
        1 for item in items for c in runner._case_of(item).expect.calls if c.tool == ANALYSIS_TOOL
    )


def analysis_call_worst(
    model: str, analysis_calls: int, repeats: int, tokens_in: int, default_max_tokens: int
) -> Decimal:
    """기대하는 대화 분석 호출의 최악 비용(출력 = Agent 경로 상한 `agent_output_cap()`). 메인 루프 기준 최악 상한에 더한다(하위 Agent 호출이라 그 곱에 들어 있지 않다)."""
    cap = max(default_max_tokens, agent_output_cap())
    return analysis_calls * repeats * call_cost(model, tokens_in, cap)


def structural_analysis_calls() -> int:
    """구조적 이론 최대 호출 가운데 대화 분석 호출 수: 소통 Agent 가 도는 도구 단계마다 최대 1회(`_calls_per_ask` 의 `2*sub` 중 추가분)."""
    from app.features.ai_assistant.knowledge import rag_chat

    from .write_tools import READ_TOOLS

    if "ask_family_chat" not in READ_TOOLS["main"]:
        return 0
    return (int(rag_chat.MAX_STEPS) - 1) * sub_agent_steps()


def structural_analysis_extra(
    model: str, cases: int, repeats: int, tokens_in: int, default_max_tokens: int
) -> Decimal:
    """구조적 이론 최대에 더할 몫: 그 가운데 분석 호출은 출력 상한이 `agent_output_cap()` 라 호출마다 (분석 상한 단가 - 기본 상한 단가)가 더 든다."""
    cap = max(default_max_tokens, agent_output_cap())
    per_call = call_cost(model, tokens_in, cap) - call_cost(model, tokens_in, default_max_tokens)
    return cases * repeats * structural_analysis_calls() * per_call


def _check_cost(inp: PreflightInput, measured_in: int) -> tuple[Check, Decimal | None]:
    from app.shared.config import settings

    from . import estimate

    name = "예상 호출 횟수·토큰·비용"
    n = len(inp.items)
    if n < 1:
        return Check(8, name, FAIL, "선택된 사례가 없어 추정할 수 없다"), None
    if inp.model not in PRICES:
        return Check(8, name, FAIL, f"단가표에 없는 모델: {inp.model}"), None
    try:
        basic, _ = estimate.build_estimate(
            inp.ledger, inp.model, n, inp.repeat, inp.calls_per_case, inp.tokens_in, inp.tokens_out
        )
    except BudgetExceeded as e:
        return Check(8, name, FAIL, f"추정 비용이 예산 상한을 넘는다: {e}"), None
    steps = _max_steps()
    tin = max(inp.tokens_in, measured_in)
    # 출력은 Agent 경로의 실제 설정 상한(`agent_max_output_tokens`)과 일반 상한 중 큰 값으로 본다(보수적). 답 검증처럼 더 낮은 상한의 호출도 같은 값으로 센다.
    tout = max(settings.anthropic_max_tokens, agent_output_cap())
    loop_worst = main_loop_worst(inp.model, n, inp.repeat, tin, tout)
    theory_calls = structural_max_calls()
    ana_calls = expected_analysis_calls(inp.items)
    ana_worst = analysis_call_worst(inp.model, ana_calls, inp.repeat, tin, tout)
    loop_worst += ana_worst  # 분석 호출(출력 상한 `agent_output_cap()`)은 하위 Agent 호출이라 메인 루프 곱에 없다: 따로 더한다
    theory = structural_worst_case(inp.model, n, inp.repeat, tin, tout) + structural_analysis_extra(
        inp.model, n, inp.repeat, tin, tout
    )
    gate = max(
        basic, loop_worst
    )  # 사전 거부 기준: 기본 가정 추정과 메인 루프 기준 최악 상한 중 큰 값
    lines = [
        f"추정치(실측 전) 기본 가정 추정 {format(basic, 'f')} USD(사례 {n} x 반복 {inp.repeat} x 사례당 {inp.calls_per_case}회, 호출당 {inp.tokens_in}/{inp.tokens_out} 토큰)",
        f"추정치(실측 전) 메인 루프 기준 최악 상한(하위 Agent 호출 포함 안 함) {format(loop_worst, 'f')} USD = 사례 {n} x 반복 {inp.repeat} x (메인 단계 상한 {steps} + 답 검증 1) = 호출 "
        f"{n * inp.repeat * (steps + 1)}회 x (입력 {tin} 토큰 + 출력 {tout} 토큰[max_tokens]) 단가"
        + (
            f" + 대화 분석 호출 {ana_calls * inp.repeat}회 x (입력 {tin} 토큰 + 출력 {max(tout, agent_output_cap())} 토큰) 단가 {format(ana_worst, 'f')} USD"
            if ana_calls
            else ""
        ),
        f"출력 상한(max_tokens): Agent 경로(메인·소통·일정·정산·대화 분석) {agent_output_cap()}(허용 천장 {AGENT_OUTPUT_CEILING}), 그 밖의 호출 {settings.anthropic_max_tokens}(일반 상한). 위 최악 비용은 큰 쪽({tout})으로 계산한다",
        f"추정치(실측 전) 구조적 이론 최대(정보용, 거부 기준 아님) {format(theory, 'f')} USD = 질문당 최대 {theory_calls}회(메인 {steps} + 검증 1 + 도구 단계 {steps - 1} x 하위 Agent 합) x 사례 {n} x 반복 {inp.repeat}",
        f"승인 금액 {format(inp.approve, 'f')} USD, 사전 거부 기준값 {format(gate, 'f')} USD(위 기본 가정 추정과 메인 루프 기준 최악 상한 중 큰 값), 단가 출처는 cost.PRICE_SOURCE",
        "위 비용은 모두 추정치다: 1건 연결 시험 후 실측 토큰·단가로 보정한다(실측 전에는 확정 비용으로 보지 않는다).",
        "하드 보장은 실행 중 호출 직전 검사다: 이번 호출의 최악 비용(입력 추정 + max_tokens)이 잔여 예산을 넘으면 그 호출을 시작하지 않는다 -> 총지출은 승인액을 한 호출의 최악 비용 이상 넘지 않는다.",
        "사전 점검 통과가 '중간에 예산 중단이 없다'를 보장하지는 않는다(구조적 이론 최대가 승인 금액을 넘으면 중단될 수 있다).",
    ]
    try:
        inp.ledger.check_estimate(gate)
    except BudgetExceeded as e:
        return Check(
            8, name, FAIL, "\n".join([*lines, f"사전 거부 기준값이 예산 상한을 넘는다: {e}"])
        ), gate
    if gate > inp.approve:
        return Check(
            8, name, FAIL, "\n".join([*lines, "사전 거부 기준값이 승인 금액보다 크다: 거부"])
        ), gate
    return Check(8, name, PASS, "\n".join(lines)), gate


def _git_ignored(path: Path) -> tuple[bool | None, str]:
    """(무시됨 여부, 설명). 저장소 밖이면 (True, ...), 확인할 수 없으면 (None, ...)."""
    cwd = Path(__file__).resolve().parent
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if top.returncode != 0:
            return None, "git 저장소를 찾을 수 없다"
        root = Path(top.stdout.strip()).resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return True, "저장소 밖(Git 추적 대상 아님)"
        res = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(resolved)],
            cwd=root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "git 을 실행할 수 없다"
    return (
        res.returncode == 0,
        "git check-ignore 로 제외 확인" if res.returncode == 0 else "Git 추적에서 제외되지 않는다",
    )


def _writable_ancestor(path: Path) -> bool:
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def _check_results(inp: PreflightInput) -> Check:
    name = "결과 저장 위치·Git 추적 제외"
    problems: list[str] = []
    root = inp.results_root
    if root.resolve() != inp.default_results.resolve():
        problems.append(
            "기본 결과 폴더 밖(--results-dir)에서는 실제 호출을 하지 않는다(누적 예산 `store.opening_spent` 가 이 폴더만 읽어서 누적이 새로 시작된다)"
        )
    run_dir = root / inp.run_id
    ignored, why = _git_ignored(run_dir)
    if ignored is not True:
        problems.append(f"결과 폴더가 Git 추적에서 제외되지 않았거나 확인할 수 없다({why})")
    if not _writable_ancestor(root):
        problems.append("결과 폴더에 쓸 수 없다")
    if run_dir.exists():
        problems.append("같은 --run-id 폴더가 이미 있다(덮어쓰지 않는다)")
    if problems:
        return Check(9, name, FAIL, "; ".join(problems))
    return Check(9, name, PASS, f"기본 결과 폴더 사용, {why}, 쓰기 가능, 같은 run-id 폴더 없음")


def run_preflight(inp: PreflightInput) -> PreflightReport:
    """모든 점검을 실행한다(앞이 실패해도 끝까지 본다). 모두 통과하면 `record` 를 만든다. 예상 밖 예외는 그 항목의 실패로 센다."""
    report = PreflightReport()

    def run(no: int, name: str, fn: Any) -> Any:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001  값·경로 없이 종류만
            report.checks.append(Check(no, name, FAIL, f"점검 중 예상 밖 오류({type(e).__name__})"))
            return None

    def add(result: Any) -> None:
        if isinstance(result, Check):
            report.checks.append(result)

    add(run(1, "API 키·설정 로딩·허가 환경변수", lambda: _check_key(inp.require_env)))
    add(run(2, "모델명·API 설정 일치", lambda: _check_model(inp.model)))
    add(run(3, "NER 필수 모드 초기화·추론", _check_ner))
    four = run(
        4, "최종 LLM 전송 본문의 개인정보 보호 경로", lambda: _fake_pass(inp) if inp.items else None
    )
    measured = 0
    if four is not None:
        report.checks.append(four[0])
        measured = four[2]
        report.person_rows = tuple(getattr(four[1], "person_rows", ()))
    elif not inp.items:
        report.checks.append(
            Check(
                4,
                "최종 LLM 전송 본문의 개인정보 보호 경로",
                FAIL,
                "선택된 사례가 없어 점검할 수 없다",
            )
        )
    add(run(5, "합성 DB·운영 DB 차단", _check_boundary))
    add(run(6, "허용 외부 호스트·네트워크 경계", _check_network))
    add(run(7, "실행 대상 사례 id·선택 결과", lambda: _check_cases(inp)))
    cost = run(8, "예상 호출 횟수·토큰·비용", lambda: _check_cost(inp, measured))
    if cost is not None:
        report.checks.append(cost[0])
        report.worst_case = cost[1]
    add(run(9, "결과 저장 위치·Git 추적 제외", lambda: _check_results(inp)))
    report.checks.sort(key=lambda c: c.no)
    if report.ok and report.worst_case is not None:
        from . import runner

        ids = frozenset(_id_of(i) for i in inp.items)
        report.record = real_gate._mint_preflight(
            inp.run_id,
            inp.approve,
            inp.split,
            ids,
            report.worst_case,
            runner.case_fingerprint(inp.items),
            inp.repeat,
            report.person_rows,
        )
    return report


def _id_of(item: Any) -> str:
    return (item.case if isinstance(item, LegacyCase) else item).id
