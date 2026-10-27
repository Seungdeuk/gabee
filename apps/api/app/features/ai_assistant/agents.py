"""메인 에이전트가 쓰는 탭 에이전트 목록. 메인은 DB 를 직접 읽지 않고 여기 도구로 탭 담당 에이전트에게 묻는다.

각 탭 에이전트의 코드는 그 기능 폴더(billing/agent.py, care/agent.py, schedule/agent/ask.py)에 있고, 여기는 이름·설명·호출만 모은다.
탭을 더 붙일 때는 `AGENTS` 에 한 줄을 더하면 된다."""

import re
from collections.abc import Callable
from dataclasses import replace

from sqlalchemy.orm import Session

from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_chat import agent as family_chat_agent
from app.features.family_group.models import User
from app.features.schedule.agent import ask as schedule_agent
from app.shared.llm.agent import AgentReply, Post

AskFn = Callable[[Session, str, User, str, Post | None], AgentReply]

AGENTS: dict[str, tuple[str, AskFn]] = {
    "ask_billing": (billing_agent.DESCRIPTION, billing_agent.ask),
    "ask_care": (care_agent.DESCRIPTION, care_agent.ask),
    "ask_family_chat": (family_chat_agent.DESCRIPTION, family_chat_agent.ask),
    "ask_schedule": (schedule_agent.DESCRIPTION, schedule_agent.ask),
}

# 답이 사용자에게 그대로 전할 수 있는 글인 탭 에이전트. 한 질문에 이것 하나만 불렀고 답이 완결이면 메인이 다시 모델을 부르지 않는다.
# (일정 에이전트의 답은 메인에게 주는 안내 글이 섞여 있어 제외한다)
DIRECT_REPLY_AGENTS = frozenset({"ask_billing", "ask_care", "ask_family_chat"})

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
    "ask_schedule 이 등록했다고 답하기 전에는 등록했다고 말하지 마세요. 일정 수정·삭제와 가족에게 공유하는 등록은 확인 카드가 "
    "사용자 화면에 나타나니, 카드의 버튼을 눌러야 반영된다고 짧게 안내하고 실행됐다고 말하지 마세요. '가족 모두에게 공유'처럼 "
    "여럿에게 공유하는 일정도 그대로 ask_schedule 로 넘기세요. "
    "가족 단체 채팅방에서 나눈 대화('채팅에서 병원 얘기 언제 했지', '요즘 채팅 요약해줘')와 가족 공동 할 일 목록 질문은 "
    "ask_family_chat 으로 물어보세요. 올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요. "
    "채팅 분석의 일정·할 일은 후보일 뿐 등록된 것이 아니라고 알려 주세요. 사용자가 그 일정 후보를 넣어 달라고 하면('그거 일정에 넣어줘', "
    "'첫 번째 일정 넣어줘') 후보의 날짜·시간·제목·장소를 합친 완전한 문장으로 ask_schedule 에 넘기고, 어느 후보인지 모르겠으면 "
    "어느 것인지 물어보세요. 넣어 달라는 말이 없으면 '일정에 넣어 드릴까요?'라고 먼저 물어보세요. 할 일 후보는 아직 등록하는 길이 없다고 알려 주세요. "
    "사용자가 후보를 가리켜 일정에 넣어 달라고 하면('마지막 거 넣어줘', '토요일 저녁 약속 잡아줘') 다시 확인하지 말고 바로 ask_schedule 로 넘기세요. "
    "날짜가 없는 후보만 날짜를 물어보세요. 일정 여러 개를 한꺼번에 넣어 달라고 하면 한 문장에 몰아 넘기지 말고 일정마다 따로 ask_schedule 을 "
    "부르고, 부른 수와 등록된 수가 같은지 확인한 뒤 모두 알려 주세요. "
    "올려 둔 영수증·고지서로 지출을 등록하거나 정산해 달라고 하면, 또는 '소아과 진료비 정산해줘'처럼 병원·약국·학원 같은 지출을 '영수증'이라는 말 없이 정산·등록해 달라고 해도, 먼저 search_knowledge 로 그 문서가 있는지 찾아 날짜·금액·제목을 읽고, "
    "그 값을 담은 완전한 문장('2026-10-24 치과 128,000원 지출로 등록해줘')을 ask_billing 에 넘기세요. 문서에 나온 날짜를 쓰고 오늘 날짜로 "
    "바꾸지 마세요. 영수증이 둘 이상이라 어느 것인지 모르면 어느 것인지 물어보세요. 정산 내역을 묻는 것이 아니라 영수증을 장부에 올리라는 뜻이면 "
    "조회가 아니라 등록으로 넘기세요. 질문과 관계없는 도구는 함께 부르지 마세요. 지출·금액을 묻는 질문은 반드시 ask_billing 으로 확인하고, search_knowledge 는 사용자가 영수증·고지서·문서를 말했을 때만 함께 쓰세요. "
    "pending_confirmation 이 결과에 없으면 제안이나 확인 카드가 만들어졌다고 말하지 마세요. "
    "'약속들 전부 넣어줘'처럼 후보 여러 개를 넣을 때는 일정 후보만 넣고 장보기·재활용 같은 할 일 후보는 넣지 마세요. "
    "'마지막 거'는 날짜가 정해진 일정 후보 중 마지막을 뜻합니다. 무엇을 넣으라는 말 없이 '넣어줘'라고만 하면 후보를 다시 보여 주고 어느 것인지 물어보세요. "
    "'전부'·'모두'·'약속들'처럼 전체를 뜻하는 말이 있을 때만 여러 개를 한꺼번에 넣으세요."
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


PROPOSAL_CLAIM = re.compile(r"확인\s*버튼|제안(합니다|했|해\s*두)")
NO_PROPOSAL_TEXT = "등록 제안이 만들어지지 않았어요. 금액·날짜·항목을 함께 다시 말씀해 주세요."


def _without_false_proposal(name: str, reply: AgentReply) -> AgentReply:
    """정산·돌봄 에이전트의 답이 '확인 버튼을 눌러야 등록돼요'라고 하는데 실제 제안(토큰)이 없으면, 그 말을 사용자에게 전하지 않는다.
    모델이 제안 도구를 부르지 않거나 실패하고도 제안했다고 글로 쓰는 경우가 있다(메인은 도구 결과의 글을 믿고 그대로 전한다)."""
    if (
        name in ("ask_billing", "ask_care")
        and reply.can_answer
        and not reply.proposals
        and PROPOSAL_CLAIM.search(reply.answer)
    ):
        return replace(reply, answer=NO_PROPOSAL_TEXT, can_answer=False)
    return reply


def call(
    db: Session, group_id: str, user: User, name: str, args: dict, post: Post | None
) -> tuple[dict, list[dict], list, list[dict]]:
    """탭 에이전트에게 묻고 (메인에게 줄 결과, 탭 에이전트가 부른 도구 기록, 쓰기 제안, 확인 카드) 를 돌려준다."""
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question 이 비어 있어요")
    reply = AGENTS[name][1](
        db, group_id, user, question, post, guarded=False
    )  # 메인 질문의 관문 한 번에 함께 센다
    reply = _without_false_proposal(name, reply)
    result = {"answer": reply.answer, "can_answer": reply.can_answer}
    if (
        reply.proposals or reply.confirmations
    ):  # 사용자 화면에 확인 버튼이 뜬다. 메인은 등록됐다고 말하면 안 된다
        result["pending_confirmation"] = [p.summary for p in reply.proposals] + [
            c["title"] for c in reply.confirmations
        ]
    return result, reply.tool_calls, reply.proposals, reply.confirmations
