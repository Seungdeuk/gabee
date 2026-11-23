"""하위 Agent 까지 포함한 통합 프롬프트 해시(val 실모델 실행 전에 고정하는 값).

실행기가 manifest 에 적는 프롬프트 해시(`cli._prompt_hash`)는 메인 어시스턴트(`ai_assistant.agents`)의 `PROMPT_NOTE` 와 도구 명세만 해시한다.
메인이 부르는 하위 Agent(가족 대화·정산·일정)의 시스템 프롬프트와 도구 명세는 그 값에 들어 있지 않아, 하위 Agent 프롬프트가 바뀌어도 manifest 해시는 그대로였다
(예: isolation-02·inject-03 수정은 가족 대화 Agent 프롬프트만 바꾼다). 이 모듈은 하위 Agent 까지 합친 해시를 따로 만든다.
기존 manifest 해시(`main`)의 계산은 바꾸지 않는다: dev 108 결과가 묶인 값이다.

계산은 DB 없이 한다(도구 명세만 만들고 실행하지 않는다). 날짜처럼 호출마다 바뀌는 값은 평가용 고정 시계로 계산해 해시에 영향을 주지 않게 한다(가족 대화·정산 프롬프트에는 오늘 날짜가 들어 있다).
"""

import hashlib
import json
from typing import Any

AGENTS = ("main", "family_chat", "billing", "schedule")


def _sha(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=repr)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _specs(tools) -> list[dict]:
    return [tool.spec() for tool in tools]


def agent_hashes() -> dict[str, str]:
    """에이전트별 해시. `main` 은 `cli._prompt_hash`(manifest 의 값)와 같다. 앱을 불러오므로 환경 준비 뒤에만 부른다."""
    from app.features.billing import agent as billing
    from app.features.family_chat import agent as family_chat
    from app.features.schedule.agent import prompts as schedule

    from . import cli
    from .clock import frozen_clock

    # 가족 대화·정산 시스템 프롬프트에는 "오늘은 <날짜>" 가 들어가 있어 날짜가 바뀌면 해시가 바뀐다(실제로 하루 만에 깨졌다).
    # 평가가 쓰는 고정 시계(`frozen_clock`)로 계산해 날짜와 무관하게 같은 값이 나오게 한다. 위에서 모듈을 먼저 불러 둔 뒤에 시계를 고정해야 그 모듈들에도 적용된다.
    # 쓰기 제안 도구까지 포함해(proposed=[]) 모든 도구의 명세를 본다. 도구 본체(run)는 만들기만 하고 부르지 않는다.
    with frozen_clock():
        out = {
            "main": cli._prompt_hash(),
            "family_chat": _sha(
                {
                    "system": family_chat.system_prompt(),
                    "tools": _specs(family_chat.build_tools(None, "g", None, None)),
                }
            ),
            "billing": _sha(
                {
                    "system": billing.system_prompt(""),
                    "tools": _specs(billing.build_tools(None, "g", None, [])),
                }
            ),
            # 일정 에이전트는 도구 호출이 아니라 구조화 출력이라, 프롬프트 모듈의 문자열·스키마 상수 전체(대문자 이름)가 곧 프롬프트다
            "schedule": _sha(
                {
                    k: v
                    for k, v in vars(schedule).items()
                    if k.isupper() and isinstance(v, (str, dict, list, tuple))
                }
            ),
        }
    assert tuple(out) == AGENTS
    return out


def integrated_hash(hashes: dict[str, str] | None = None) -> str:
    """에이전트별 해시를 합친 통합 해시. 어느 한 Agent 의 프롬프트·도구 명세가 바뀌어도 값이 바뀐다."""
    return _sha(hashes if hashes is not None else agent_hashes())
