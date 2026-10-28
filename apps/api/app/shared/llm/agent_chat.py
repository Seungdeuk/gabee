"""탭 에이전트와 직접 대화하는 공통 처리(AI 끄기 안내, 앞 대화 전달)와 제안 확인. 메인 에이전트를 거치지 않는다.

각 탭 라우터는 자기 탭의 `ask` 함수를 넘겨 `chat` 만 부르면 된다. AI 동의·한도·사용 기록은 `ask` 안에서
`agent_guard`(팀 공통 `ai_guard`)가 처리한다."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings

from . import proposals
from .agent import AgentReply
from .schemas import AgentChatIn, AgentChatOut, AgentConfirmIn, AgentConfirmOut, ProposalOut

FALLBACK_REPLY = "지금은 AI 연결이 꺼져 있어서 답할 수 없어요. 앱 화면에서 직접 확인해 주세요."

AskFn = Callable[..., AgentReply]


def chat(db: Session, group_id: str, user: User, body: AgentChatIn, ask: AskFn) -> AgentChatOut:
    if not settings.anthropic_api_key:
        return AgentChatOut(reply=FALLBACK_REPLY, source="fallback", tool_calls=[])
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
    claims = proposals.consume(db, body.token, tab, user.id, group_id)
    try:
        execute(db, group_id, user, claims["act"], claims["args"])
    except Exception:
        proposals.release(db, claims["jti"])
        raise
    return AgentConfirmOut(ok=True, summary=claims["summary"])
