"""메인 에이전트가 쓰는 탭 에이전트 목록. 메인은 DB 를 직접 읽지 않고 여기 도구로 탭 담당 에이전트에게 묻는다.

각 탭 에이전트의 코드는 그 기능 폴더(billing/agent.py, care/agent.py)에 있고, 여기는 이름·설명·호출만 모은다.
탭을 더 붙일 때는 `AGENTS` 에 한 줄을 더하면 된다."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.shared.llm.agent import AgentReply, Post

AskFn = Callable[[Session, str, User, str, Post | None], AgentReply]

AGENTS: dict[str, tuple[str, AskFn]] = {
    "ask_billing": (billing_agent.DESCRIPTION, billing_agent.ask),
    "ask_care": (care_agent.DESCRIPTION, care_agent.ask),
}

PROMPT_NOTE = (
    "지출·정산·구독·용돈 질문은 ask_billing, 돌봄 항목·식단·위치 질문은 ask_care 로 담당 에이전트에게 물어보세요. "
    "당신은 가계·돌봄 데이터를 직접 볼 수 없으니 추측하지 말고, 질문 내용을 한국어 문장으로 그대로 넘기세요(기간이나 "
    "사람 이름이 있으면 포함). 돌려받은 답의 숫자와 사실은 바꾸지 말고 전하세요. 두 탭에 걸친 질문이면 둘 다 물어보세요. "
    "can_answer 가 false 면 답을 지어내지 말고 지금은 확인하지 못했다고 알려 주세요. "
    "등록·기록 요청도 같은 담당 에이전트에게 넘기세요. pending_confirmation 이 있으면 아직 실행된 것이 아니라 "
    "사용자가 화면의 확인 버튼을 눌러야 반영된다고 알려 주세요."
)


def tool_specs() -> list[dict]:
    return [
        {
            "name": name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "담당 에이전트에게 물어볼 내용을 완전한 한국어 문장으로",
                    }
                },
                "required": ["question"],
            },
        }
        for name, (description, _) in AGENTS.items()
    ]


def is_agent_tool(name: str) -> bool:
    return name in AGENTS


def call(
    db: Session, group_id: str, user: User, name: str, args: dict, post: Post | None
) -> tuple[dict, list[dict], list]:
    """탭 에이전트에게 묻고 (메인에게 줄 결과, 탭 에이전트가 부른 도구 기록, 쓰기 제안) 을 돌려준다."""
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question 이 비어 있어요")
    reply = AGENTS[name][1](
        db, group_id, user, question, post, guarded=False
    )  # 메인 질문의 관문 한 번에 함께 센다
    result = {"answer": reply.answer, "can_answer": reply.can_answer}
    if reply.proposals:  # 사용자 화면에 확인 버튼이 뜬다. 메인은 등록됐다고 말하면 안 된다
        result["pending_confirmation"] = [p.summary for p in reply.proposals]
    return result, reply.tool_calls, reply.proposals
