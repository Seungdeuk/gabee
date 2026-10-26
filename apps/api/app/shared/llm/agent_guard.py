"""탭 에이전트의 질문 하나를 팀 공통 AI 관문(`ai_guard.run`) 아래에서 실행한다.

관문이 해 주는 일: 가족 그룹의 AI 동의(소유자·관리자가 켬) 확인, 사용자 쿨다운과 사용자·가족 하루 한도, 가족 동시 실행 제한,
사용 기록(원문 없음: 시각·기능·토큰·결과 상태). 질문 한 번에 모델을 여러 번 부르면 실제 호출 수(`calls`)를 사용 기록·한도에 센다.
메인 채팅 안에서 탭 에이전트를 부를 때는 메인 질문이 이미 관문 한 번을 지나고 같은 `post` 로 호출 수를 세므로 여기서 다시 지나지 않는다(`guarded=False`).
정산·돌봄 에이전트는 기본 한도·일정 에이전트와 따로 센다(`ai_tab_agent_*` 설정).

결과는 캐시하지 않는다(`cache_key=None`): 그때그때 DB 를 읽은 답이고, 쓰기 제안 토큰은 한 번만 쓸 수 있어서다(캐시에 가계·위치 내용이 복사되는 것도 막는다).
사용자 문장은 외부로 나가기 전에 개인정보를 가린다(일정 에이전트와 같은 `mask_text`). 도구 결과(이름·금액·좌표)는 답에 필요해서 가리지 않는다.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

# 일정 에이전트(schedule/agent/chat.py)와 같은 마스킹 함수를 쓴다. 이 함수의 위치나 이름을 바꾸면 여기도 고쳐야 한다.
from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.config import settings

from . import client as llm
from .agent import AgentReply

log = logging.getLogger(__name__)

BILLING_FEATURE = "billing_agent"
CARE_FEATURE = "care_agent"
FEATURES = (BILLING_FEATURE, CARE_FEATURE)


def register() -> None:
    ai_guard.register_bucket(
        "tab_agent",
        ai_guard.Limits(
            settings.ai_tab_agent_cooldown_seconds,
            settings.ai_tab_agent_max_calls_per_user_per_day,
            settings.ai_tab_agent_max_calls_per_group_per_day,
        ),
        FEATURES,
    )


register()


@dataclass(frozen=True)
class _Usage:
    """ai_guard.run 이 쓰는 응답 요약(JsonResult 와 같은 이름 + 실제 호출 수 calls)."""

    data: dict
    input_tokens: int
    output_tokens: int
    model: str
    calls: int


def prepare(question: str, history: list[dict] | None) -> tuple[str, list[dict] | None]:
    """외부로 보내는 사용자 문장(질문과 앞 대화)의 개인정보를 가린다."""
    masked = [{**turn, "text": mask_text(turn["text"])} for turn in history] if history else history
    return mask_text(question), masked


def run_turn(
    db: Session,
    user_id: str,
    group_id: str,
    feature: str,
    turn: Callable[[], AgentReply],
    guarded: bool = True,
) -> AgentReply:
    """turn() 이 돌려준 답을 관문을 거쳐 얻는다. AI 동의가 꺼져 있으면 403 `ai_not_enabled`, 한도에 걸리면 429,
    모델 호출이 실패하면 503 `llm_failed`(ApiError)로 끝난다.

    guarded=False 는 이미 관문 아래에서 도는 호출(메인 채팅이 탭 에이전트를 부르는 경우)용이다. 관문은 가족 동시 실행을
    1건으로 제한하므로 안에서 다시 지나면 막힌다. 모델 호출 수는 바깥이 같은 `post` 로 센다."""
    if not guarded:
        return turn()
    holder: dict[str, AgentReply] = {}

    def call():
        reply = turn()
        if not reply.can_answer:
            # 사용자에게는 일반 오류만 가므로 원인(HTTP 상태·API 오류 종류)은 서버 로그에 남긴다. 질문·답·키는 담기지 않는다
            log.warning("%s 에이전트 모델 호출 실패: %s", feature, reply.answer)
            error = llm.LLMUnavailable(reply.answer)
            error.calls = max(1, reply.calls)  # 실패한 호출도 한도에 센다
            raise error
        holder["reply"] = reply
        usage = _Usage(
            {}, reply.input_tokens, reply.output_tokens, reply.model, max(1, reply.calls)
        )
        return {"answered": True}, usage

    ai_guard.run(
        db,
        user_id=user_id,
        group_id=group_id,
        feature=feature,
        cache_key=None,
        call=call,
    )
    return holder["reply"]
