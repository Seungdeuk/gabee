"""메인 에이전트가 쓰는 탭 에이전트 목록. 메인은 DB 를 직접 읽지 않고 여기 도구로 탭 담당 에이전트에게 묻는다.

각 탭 에이전트의 코드는 그 기능 폴더(billing/agent.py, care/agent.py, schedule/agent/ask.py)에 있고, 여기는 이름·설명·호출만 모은다.
탭을 더 붙일 때는 `AGENTS` 에 한 줄을 더하면 된다."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.features.schedule.agent import ask as schedule_agent
from app.shared.llm.agent import AgentReply, Post

AskFn = Callable[[Session, str, User, str, Post | None], AgentReply]

AGENTS: dict[str, tuple[str, AskFn]] = {
    "ask_billing": (billing_agent.DESCRIPTION, billing_agent.ask),
    "ask_care": (care_agent.DESCRIPTION, care_agent.ask),
    "ask_schedule": (schedule_agent.DESCRIPTION, schedule_agent.ask),
}

PROMPT_NOTE = (
    "지출·정산·구독·용돈 질문은 ask_billing, 돌봄 항목·식단·위치 질문은 ask_care 로 담당 에이전트에게 물어보세요. "
    "당신은 가계·돌봄 데이터를 직접 볼 수 없으니 추측하지 말고, 질문 내용을 한국어 문장으로 그대로 넘기세요(기간이나 "
    "사람 이름이 있으면 포함). 돌려받은 답의 숫자와 사실은 바꾸지 말고 전하세요. 두 탭에 걸친 질문이면 둘 다 물어보세요. "
    "can_answer 가 false 면 답을 지어내지 말고 지금은 확인하지 못했다고 알려 주세요. "
    "등록·기록 요청도 같은 담당 에이전트에게 넘기세요. pending_confirmation 이 있으면 아직 실행된 것이 아니라 "
    "사용자가 화면의 확인 버튼을 눌러야 반영된다고 알려 주세요. "
    "ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나, 사용자가 일정에 넣어 달라고 분명히 말한 것을 등록할 때만 쓰세요. "
    "문장에 '일정'이라는 낱말이 있다는 이유로 보내지 마세요. ask_schedule 은 올려 둔 문서·영수증·안내문에 적힌 날짜를 모릅니다. "
    "학교 행사, 항공권·숙박·예약 확인서, 납기·만기·결제일처럼 문서에 적힌 날짜를 묻는 질문은 search_knowledge 로 먼저 찾으세요. "
    "ask_schedule 이 일정 탭에서 못 찾았다고 하면 답하기 전에 search_knowledge 로 올린 기록에서도 찾아보세요. "
    "'잡아줘', '등록해줘', '넣어줘', '추가해줘'처럼 일정으로 넣어 달라고 분명히 말하면 바로 ask_schedule 로 넘기되, 날짜·시간·제목을 "
    "합친 완전한 문장으로 넘기고 '내일' 같은 날짜 말은 바꾸지 마세요. "
    "날짜와 할 일만 말했을 뿐 일정에 넣어 달라는 말이 없으면('엄마 생신이야', '내일 병원 가야 돼') 등록하지 말고 "
    "'일정에 넣어 드릴까요?'라고 먼저 물어보세요. 사용자가 그러라고 하면 그때 ask_schedule 로 넘기세요. "
    "'이거 일정에 넣어줘'의 '이거'가 방금 올린 문서나 앞서 찾은 기록이면 search_knowledge 로 그 기록의 날짜·제목을 읽고 "
    "그 내용을 담은 완전한 문장으로 ask_schedule 에 넘기세요. "
    "ask_schedule 이 정보가 더 필요하다며 질문을 돌려주면 그 질문을 사용자에게 그대로 전하고, 사용자가 답하면 앞서 말한 "
    "날짜·시간·제목을 합쳐 하나의 완전한 문장으로 다시 넘기세요. 이미 등록한 일정을 같은 요청으로 다시 등록하지 마세요. "
    "ask_schedule 이 등록했다고 답하기 전에는 등록했다고 말하지 마세요. 일정 수정·삭제와 가족에게 공유하는 등록은 이 대화에서 "
    "실행되지 않으니 일정 화면에서 확인해 달라고 안내하세요."
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
