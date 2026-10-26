"""탭 에이전트와 직접 대화하는 공통 처리(AI 끄기 안내, 하루 호출 한도, 앞 대화 전달). 메인 에이전트를 거치지 않는다.

각 탭 라우터는 자기 탭의 `ask` 함수를 넘겨 `chat` 만 부르면 된다. 한도는 프로세스 메모리 기준이라 재시작하면 0 으로 돌아간다."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.rate_limit import FailureLimiter

from . import proposals
from .agent import AgentReply
from .schemas import AgentChatIn, AgentChatOut, AgentConfirmIn, AgentConfirmOut, ProposalOut

DAILY_LIMIT = 100  # 사용자 한 명이 하루에 탭 에이전트와 직접 나눌 수 있는 대화 수
DAY = 86400
FALLBACK_REPLY = "지금은 AI 연결이 꺼져 있어서 답할 수 없어요. 앱 화면에서 직접 확인해 주세요."

limiter = FailureLimiter(retention=DAY)

AskFn = Callable[..., AgentReply]


def chat(db: Session, group_id: str, user: User, body: AgentChatIn, ask: AskFn) -> AgentChatOut:
    if not settings.anthropic_api_key:
        return AgentChatOut(reply=FALLBACK_REPLY, source="fallback", tool_calls=[])
    if limiter.retry_after(user.id, DAILY_LIMIT, DAY):
        raise ApiError(
            429,
            "daily_limit",
            "오늘은 가비에게 물어볼 수 있는 횟수를 모두 썼어요. 내일 다시 물어봐 주세요",
        )
    limiter.record(user.id)
    history = [t.model_dump() for t in body.history]
    reply = ask(db, group_id, user, body.message, history=history)
    return AgentChatOut(
        reply=reply.answer,
        source="ai" if reply.can_answer else "fallback",
        tool_calls=[c["name"] for c in reply.tool_calls],
        proposals=to_out(reply.proposals),
    )


def to_out(items: list) -> list[ProposalOut]:
    return [ProposalOut(token=p.token, summary=p.summary, tab=p.tab) for p in items]


ExecuteFn = Callable[[Session, str, User, str, dict], None]


def confirm(
    db: Session, group_id: str, user: User, body: AgentConfirmIn, tab: str, execute: ExecuteFn
) -> AgentConfirmOut:
    """사용자가 확인한 제안을 실행한다. 토큰이 이 사용자·이 가족·이 탭의 것인지, 만료·재사용이 아닌지 먼저 본다.
    인자는 실행 직전에 해당 탭의 스키마로 다시 검증한다."""
    claims = proposals.consume(body.token, tab, user.id, group_id)
    try:
        execute(db, group_id, user, claims["act"], claims["args"])
    except Exception:
        proposals.release(claims["jti"])
        raise
    return AgentConfirmOut(ok=True, summary=claims["summary"])
