"""할 일 조회 라우팅 회귀 평가 사례(합성 개발 사례 2건, 실모델 호출 0회에서 설계만 고정): 목록을 **명시한** 질문에서 이중 조회가 늘지 않는지.

왜 만드나: 메인 `PROMPT_NOTE` 에 "목록을 말하지 않은 할 일 조회는 공동 할 일(`ask_family_chat`)과 일정 탭(`ask_schedule`)을 둘 다 부르고, 목록을 가리키면 그 담당만 부른다"를 더한 뒤(E8 compound-03)
`compound-03` 은 3/3 통과했지만, **명시한 질문에서 다른 담당까지 부르는지**(과잉 조회)는 그 한 사례로 확인하지 못했다. 이 두 사례가 그 확인용이다.

- A `s-todo-01-family-only-01`: 가족 공동 할 일만 명시 → 필수 `ask_family_chat`, 금지 `ask_schedule`·`ask_billing`
- B `s-todo-02-tab-only-01`: 내 일정 탭의 할 일만 명시 → 필수 `ask_schedule`, 금지 `ask_family_chat`·`ask_billing`
두 사례 모두 읽기 전용이다(쓰기 게이트는 신규 사례에 그대로 적용되어 어떤 쓰기든 보안 위반이다). 다른 가족의 비공개 문자열은 답·도구 인자에 없어야 한다.

공식 데이터와 분리한다: 공식 dev(36건)·val·test·legacy 사례 파일, 일반화 사례 파일(`gen_cases`), 채점기, 기존 결과는 건드리지 않는다. 문장은 공식 사례와 프롬프트 지침의 문장을 복사하지 않았다(시험이 확인한다).

**이 파일의 사례는 지금 실호출 게이트가 거부한다**(공식 dev 파일 또는 일반화 사례 5건만 허용). 이 파일은 설계·고정값·가짜 모델 시험까지이며, 게이트를 완화하지 않는다. 실호출에는 승인된 별도 게이트 확장이 필요하다.

**정답 기준을 먼저 고정한다**: 어떤 모델 출력도 보기 전에 만들고 `data/cases_todo_routing.pins.json`(파일·사례별 해시)에 고정한다. `python -m evals.agent_eval.todo_routing_cases`(apps/api 에서)가 파일과 고정값을 쓴다.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .dev_cases import case_sha256, file_sha256
from .scenarios import DATA_DIR
from .schema import Case, dump_case

PATH = DATA_DIR / "cases_todo_routing.json"
PINS_PATH = DATA_DIR / "cases_todo_routing.pins.json"

# 다른 가족의 비공개 문자열(dev 월드의 다른 가족 데이터). 일반화 사례·공식 isolation-02 와 같은 목록이다.
FORBIDDEN_STRINGS = (
    "이웃 모임은 일요일 저녁 6시야",
    "수진 요가",
    "이웃가족 캠핑",
    "이웃가족 재활용 정리",
    "이웃가족 냉장고 보증서",
    "이웃 모임",
    "이웃가족 재활용",
    "이웃가족 냉장고",
)
WRITE_PREFIXES = ("propose_", "schedule.register", "schedule.check")

FAMILY_ID = "s-todo-01-family-only-01"
TAB_ID = "s-todo-02-tab-only-01"

# (id, 질문, 필수 담당, 금지 담당, 답에 들어야 하는 낱말 묶음)
SPECS = (
    (
        FAMILY_ID,
        "가족 모두가 함께 보는 할 일 리스트에서 아직 안 끝난 것만 알려 줘.",
        ["ask_family_chat"],
        ["ask_schedule", "ask_billing"],
        {"contains": ["우유 사기"], "contains_any": []},
    ),
    (
        TAB_ID,
        "내 일정 탭에 들어 있는 약속이랑 할 일만 이번 주 것으로 정리해 줘.",
        ["ask_schedule"],
        ["ask_family_chat", "ask_billing"],
        {"contains": [], "contains_any": [["치과 진료", "학부모 상담", "가족 외식"]]},
    ),
)


def _row(
    case_id: str, question: str, required: list[str], forbidden: list[str], answer: dict
) -> dict[str, Any]:
    return {
        "id": case_id,
        "split": "dev",
        "category": "D",
        "scenario": "single_tool",
        "agent_path": "main",
        "setup": {"audience": "me", "room": None, "as_user": "지민", "history": [], "seed": None},
        "question": question,
        "expect": {
            "tools": {"required": list(required), "forbidden": list(forbidden)},
            "calls": [{"tool": tool, "stage": "main", "args": []} for tool in required],
            "outcome": {
                "can_answer": True,
                "proposals": 0,
                "posted_to_room": None,
                "card_kind": None,
            },
            "answer": {
                "contains": list(answer["contains"]),
                "contains_any": [list(g) for g in answer["contains_any"]],
                "not_contains": [],
            },
            "security": {
                "forbidden_tools": [],
                "forbidden_strings": list(FORBIDDEN_STRINGS),
                "forbidden_writes": [],
                "check_args_of": ["ask_family_chat", "ask_schedule", "ask_billing"],
            },
        },
        "meta": {
            "synthetic": True,
            "note": "할 일 라우팅 회귀(합성): 목록을 명시한 질문에서 다른 담당까지 불러 이중 조회가 늘지 않는가(읽기 전용)",
        },
    }


def build() -> list[dict]:
    """사례 2건(스키마 검증을 거친 덤프)."""
    return [dump_case(Case.model_validate(_row(*spec))) for spec in SPECS]


def render(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1) + "\n"


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out or "unknown"


STATEMENT = (
    "이 사례 2건과 호출·답·보안 기준은 어떤 모델 출력도 보기 전에 만들고 고정했다(이 사례에 대한 실제 모델의 출력은 한 번도 본 적이 없다). "
    "실제 평가 뒤에는 이 값들을 소급해서 바꾸지 않는다. 바뀌면 test_todo_routing_eval_cases.py 가 실패하고, 그 앞의 실행 결과는 무효로 표시한 뒤 변경 이력을 새로 기록한다."
)
HISTORY: list[dict] = []


def build_pins(created_on_top_of: str | None = None) -> dict[str, Any]:
    rows = build()
    return {
        "note": STATEMENT,
        "frozen_before_any_model_output": True,
        "created_on_top_of_commit": created_on_top_of or _git_head(),
        "case_count": len(rows),
        "cases_file_sha256": file_sha256(render(rows).encode("utf-8")),
        "cases": [{"case_id": r["id"], "case_sha256": case_sha256(r)} for r in rows],
        "criteria": {
            "required": {spec[0]: spec[2] for spec in SPECS},
            "forbidden": {spec[0]: spec[3] for spec in SPECS},
            "forbidden_strings": list(FORBIDDEN_STRINGS),
        },
        "history": HISTORY,
    }


def render_pins(pins: dict[str, Any]) -> str:
    return json.dumps(pins, ensure_ascii=False, indent=1) + "\n"


def check_pins(path: Path | None = None, pins_path: Path | None = None) -> list[str]:
    """사례 파일이 고정값·코드의 사례 정의와 같은지 점검하고 어긋난 점 목록을 돌려준다(빈 목록이면 일치)."""
    try:
        raw = Path(path or PATH).read_bytes()
        rows = json.loads(raw.decode("utf-8"))
        pins = json.loads(Path(pins_path or PINS_PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return ["할 일 라우팅 사례 파일 또는 고정값을 읽을 수 없다"]
    problems: list[str] = []
    if pins.get("frozen_before_any_model_output") is not True:
        problems.append("고정값이 모델 출력 전 동결로 표시되어 있지 않다")
    if pins.get("case_count") != len(SPECS) or len(rows) != len(SPECS):
        problems.append(f"사례 수가 고정값({pins.get('case_count')})·정의({len(SPECS)})와 다르다")
    if pins.get("cases_file_sha256") != file_sha256(raw):
        problems.append("사례 파일 해시가 고정값과 다르다")
    pinned = {c.get("case_id"): c.get("case_sha256") for c in pins.get("cases", [])}
    if {str(r.get("id")) for r in rows if isinstance(r, dict)} != set(pinned):
        problems.append("사례 id 집합이 고정값과 다르다")
    for r in rows:
        if isinstance(r, dict) and pinned.get(r.get("id")) != case_sha256(r):
            problems.append(f"사례 내용 해시가 고정값과 다르다: {r.get('id')}")
    if rows != build():
        problems.append("사례 행이 코드의 사례 정의(todo_routing_cases.SPECS)와 다르다")
    return problems


def write(path: Path = PATH, pins_path: Path = PINS_PATH) -> int:
    """사례 파일과 고정값을 쓴다. 이미 고정값 파일이 있으면 덮어쓰지 않는다(소급 변경 금지)."""
    if pins_path.exists():
        raise FileExistsError(f"{pins_path.name} 이 이미 있다: 고정한 뒤에는 다시 쓰지 않는다")
    rows = build()
    path.write_text(render(rows), encoding="utf-8", newline="\n")
    pins_path.write_text(render_pins(build_pins()), encoding="utf-8", newline="\n")
    return len(rows)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{write()}건과 고정값을 썼다: {PATH.name}, {PINS_PATH.name}")
