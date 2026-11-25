"""메인 에이전트가 쓰는 탭 에이전트 목록. 메인은 DB 를 직접 읽지 않고 여기 도구로 탭 담당 에이전트에게 묻는다.

각 탭 에이전트의 코드는 그 기능 폴더(billing/agent.py, family_chat/agent.py, schedule/agent/ask.py)에 있고, 여기는 이름·설명·호출만 모은다.
탭을 더 붙일 때는 `AGENTS` 에 한 줄을 더하면 된다."""

import re
from collections.abc import Callable
from dataclasses import replace

from sqlalchemy.orm import Session

from app.features.billing import agent as billing_agent

# from app.features.care import agent as care_agent  # 돌봄 에이전트를 메인에서 뺐다(AGENTS 참고)
from app.features.family_chat import agent as family_chat_agent
from app.features.family_group.models import User
from app.features.schedule.agent import ask as schedule_agent
from app.shared import ai_guard
from app.shared.llm.agent import AgentReply, Post
from app.shared.llm.agent_guard import BILLING_FEATURE, FAMILY_CHAT_FEATURE

AskFn = Callable[[Session, str, User, str, Post | None], AgentReply]

AGENTS: dict[str, tuple[str, AskFn]] = {
    "ask_billing": (billing_agent.DESCRIPTION, billing_agent.ask),
    # 돌봄 에이전트는 팀 회의 결과로 지갑 탭 개편 동안 메인 에이전트에서 뺀다(care/agent.py 는 이미 지워졌고, 다시 붙일 때는 새로 만든다).
    # "ask_care": (care_agent.DESCRIPTION, care_agent.ask),
    "ask_family_chat": (family_chat_agent.DESCRIPTION, family_chat_agent.ask),
    "ask_schedule": (schedule_agent.DESCRIPTION, schedule_agent.ask),
}

# 탭 에이전트 → 사용 기록(ai_usage_logs.feature) 이름. 각 탭에서 직접 쓸 때 남는 이름과 같게 둔다
USAGE_FEATURES = {
    "ask_billing": BILLING_FEATURE,
    "ask_family_chat": FAMILY_CHAT_FEATURE,
    "ask_schedule": "schedule_chat",  # schedule/agent/chat.py 의 FEATURE
}

# 답이 사용자에게 그대로 전할 수 있는 글인 탭 에이전트. 한 질문에 이것 하나만 불렀고 답이 완결이면 메인이 다시 모델을 부르지 않는다.
# (일정 에이전트의 답은 메인에게 주는 안내 글이 섞여 있어 제외한다)
DIRECT_REPLY_AGENTS = frozenset(
    {"ask_billing", "ask_family_chat", "ask_schedule"}
)  # "ask_care" 는 주석 처리(위 AGENTS 참고)
USER_TEXT_AGENTS = frozenset(
    {"ask_schedule"}
)  # 직통 응답에 answer 가 아니라 사용자에게 줄 글(direct_answer)을 쓰는 에이전트

PROMPT_NOTE = (
    # 돌봄 문장은 지갑 탭 개편 동안 뺐다. 원래: "지출·정산·구독·용돈 질문은 ask_billing, 돌봄 항목 질문은 ask_care 로 담당 에이전트에게 물어보세요. 당신은 가계·돌봄 데이터를 직접 볼 수 없으니"
    "지출·정산·용돈 질문은 ask_billing 으로 담당 에이전트에게 물어보세요. 구독·통신비·결제일은 지금 확인할 수 없으니 모른다고 답하세요. 돌봄 항목(데일리 체크 등)은 지금 확인할 수 없으니 모른다고 답하세요. "
    "당신은 가계 데이터를 직접 볼 수 없으니 추측하지 말고, 질문 내용을 한국어 문장으로 그대로 넘기세요(기간이나 "
    "사람 이름이 있으면 포함). 돌려받은 답의 숫자와 사실은 바꾸지 말고 전하세요. 질문이 두 영역을 직접 묻는 복합 요청일 때만 필요한 담당을 각각 물어보세요. "
    "can_answer 가 false 면 답을 지어내지 말고 지금은 확인하지 못했다고 알려 주세요. "
    "등록·기록 요청도 같은 담당 에이전트에게 넘기세요. pending_confirmation 이 있으면 아직 실행된 것이 아니라 "
    "사용자가 화면의 확인 버튼을 눌러야 반영된다고 알려 주세요. "
    # 대상이 정해지지 않은 지출 삭제·수정(ambig-02): 메인이 '가장 최근 지출을 찾아 삭제 확인을 요청해 달라'로 질문을 바꿔 넘기면 정산 담당이 그 지출을 골라 제시한다.
    # 평가 사례의 질문을 예시로 넣지 않는다(`test_main_prompt_ambiguous_delete.py` 가 막는다).
    "지출을 지우거나 고쳐 달라는 요청이 제목·금액·날짜 어느 것으로도 대상을 가리키지 않았거나('그거', '아까 그 지출'처럼 가리키는 말뿐) 앞 대화로도 정해지지 않으면, "
    "어느 지출인지 제목·날짜·금액 중 아는 것을 ask_billing 을 부르기 전에 사용자에게 먼저 물어보세요. "
    "가장 최근 지출이나 다른 지출을 임의로 골라 찾아서 알려 달라고 넘기거나 삭제 확인 카드를 요청하지 마세요. "
    "제목·금액·날짜 중 하나로 가리킨 요청은 지금처럼 그대로 ask_billing 으로 넘기세요. "
    "ask_schedule 은 '일정 탭에 이미 입력된 일정'을 조회하거나, 사용자가 일정에 넣어 달라고 분명히 말한 것을 등록할 때만 쓰세요. "
    "문장에 '일정'이라는 낱말이 있다는 이유로 보내지 마세요. ask_schedule 은 올려 둔 문서·영수증·안내문에 적힌 날짜를 모릅니다. "
    "학교 행사, 항공권·숙박·예약 확인서, 납기·만기·결제일처럼 문서에 적힌 날짜를 묻는 질문은 search_knowledge 로 먼저 찾으세요. "
    "ask_schedule 이 일정 탭에서 못 찾았다고 하면 답하기 전에 search_knowledge 로 올린 기록에서도 찾아보세요. "
    "ask_billing 이 해당 지출·정산 기록이 없다고 하면 답하기 전에 search_knowledge 로 올린 문서(정산표, 영수증, 청구서)에서도 찾아보세요. "
    "'잡아줘', '등록해줘', '넣어줘', '추가해줘'처럼 일정으로 넣어 달라고 분명히 말하면 바로 ask_schedule 로 넘기되, 날짜·시간·제목을 "
    "합친 완전한 문장으로 넘기고 '내일' 같은 날짜 말은 바꾸지 마세요. "
    "날짜와 할 일만 말했을 뿐 일정에 넣어 달라는 말이 없으면('엄마 생신이야', '내일 병원 가야 돼') 등록하지 말고 "
    "'일정에 넣어 드릴까요?'라고 먼저 물어보세요. 사용자가 그러라고 하면 그때 ask_schedule 로 넘기세요. "
    "'이거 일정에 넣어줘'의 '이거'가 방금 올린 문서나 앞서 찾은 기록이면 search_knowledge 로 그 기록의 날짜·제목을 읽고 "
    "그 내용을 담은 완전한 문장으로 ask_schedule 에 넘기세요. 그 날짜에 하는 일의 시각과 장소가 기록에 적혀 있으면 함께 읽어 문장에 담고"
    "(예: '2026-11-13 08:40 국립중앙박물관 현장체험학습을 일정에 넣어줘'), 메모는 문서의 핵심 내용만 한두 문장으로 적도록 덧붙이세요"
    "(시각·장소를 메모에 되풀이하지 않고, 이름·연락처·주소는 쓰지 않습니다). 기록에 없는 시각·장소는 지어내지 마세요. "
    "이미 있는 일정을 '지워줘', '바꿔줘', '미뤄줘'처럼 고치거나 지워 달라는 말은 앞 대화의 '그거'·'그 일정'을 일정 제목과 날짜로 풀어 "
    "'11월 18일 치과 일정을 지워줘'처럼 지우기·바꾸기 문장 그대로 ask_schedule 에 넘기세요. 있는지 찾아 알려 달라는 조회 문장으로 바꾸지 마세요. "
    "ask_schedule 이 정보가 더 필요하다며 질문을 돌려주면 그 질문을 사용자에게 그대로 전하고, 사용자가 답하면 앞서 말한 "
    "날짜·시간·제목을 합쳐 하나의 완전한 문장으로 다시 넘기세요. 이미 등록한 일정을 같은 요청으로 다시 등록하지 마세요. "
    "ask_schedule 이 등록했다고 답하기 전에는 등록했다고 말하지 마세요. 일정 삭제는 확인 카드가 나타나니, "
    "카드의 버튼을 눌러야 반영된다고 짧게 안내하고 실행됐다고 말하지 마세요. 등록(공유 등록 포함)과 수정(공유 대상 변경 포함)은 카드 없이 "
    "바로 실행되니 ask_schedule 이 돌려준 안내를 그대로 전하고 버튼을 누르라고 하지 마세요. 같은 이름의 일정이 여럿이거나 가족이 모호하면 선택 카드가 "
    "나타나니, 카드에서 항목을 체크하고 버튼을 누르면 바로 처리된다고만 짧게 안내하고 어느 쪽인지 글로 다시 묻지 마세요. '가족 모두에게 공유'처럼 "
    "여럿에게 공유하는 일정도 그대로 ask_schedule 로 넘기세요. "
    "가족에게 일을 같이 해 달라고 보내는 부탁('엄마한테 장 봐달라고 부탁해줘'), 보낸 부탁의 받는 사람 바꾸기·취소, "
    "부탁의 상세·수락 현황 질문('내가 보낸 부탁 누가 수락했어?')도 ask_schedule 로 넘기세요. 부탁을 취소하는 것은 "
    "확인 카드의 버튼을 눌러야 반영되니 실행됐다고 말하지 말고, 부탁 보내기·받는 사람 바꾸기·메모 바꾸기는 바로 실행되니 "
    "ask_schedule 이 돌려준 안내를 그대로 전하세요. 부탁을 보낼 때는 누구에게·무엇을·언제를 담은 완전한 문장으로 넘기세요. "
    "가족 단체 채팅방에서 나눈 대화('채팅에서 병원 얘기 언제 했지', '요즘 채팅 요약해줘')와 가족 공동 할 일 목록 질문은 "
    "ask_family_chat 으로 물어보세요. "
    # 출처 판별(이중 호출 개선): 질문이 가리키는 출처가 분명한데 다른 담당까지 함께 부르면 호출·비용·시간이 늘고, 방에서는 일정 담당이 끼어 비공개 일정 제목이 섞일 수 있다.
    # 출처가 하나로 정해지면 그 담당만, 불분명한 할 일 조회나 직접 묻는 복합 요청일 때만 여럿(아래 compound-03 규칙은 그 예외로 그대로 둔다). 평가 질문을 예시로 넣지 않는다(`test_main_prompt_source_routing.py` 가 막는다).
    "질문이 가리키는 출처가 하나로 정해지면 그 출처의 담당만 부르고 다른 담당은 함께 부르거나 보충하려고 더 부르지 마세요. 일정 탭에 입력된 일정(날짜·시각·장소)이나 일정 탭 자체를 묻는 질문은 ask_schedule 만, "
    "가족 단체 채팅의 대화 내용이나 가족 공동 할 일을 묻는 질문은 ask_family_chat 만 부르세요. 채팅에서 뽑힌 약속·할 일 후보는 일정 탭에 등록된 것이 아니니 일정 탭 조회와 섞지 말고, "
    "사용자가 일정 탭의 상태를 직접 묻거나 등록을 말할 때만 ask_schedule 을 부르세요. 사용자가 말한 출처가 가장 우선입니다. 아래에 방 대화 내용이 함께 붙어 있다는 사실은 "
    "출처를 말하지 않았을 때만 보조 단서로 쓰세요: 가족 채팅방에서 한 할 일 질문은 일정 탭이 아니라 ask_family_chat 으로 물어봅니다. "
    "대화에서 이야기했거나 정한 내용(목록 포함)을 찾는 질문은 등록된 공동 할 일 조회로 바꾸지 말고 대화를 찾는 질문 그대로 넘기세요. "
    "가족 채팅방에서도 사용자가 일정 탭의 일정(공동 일정 포함)을 말하면 ask_schedule 로 확인하세요. "
    # 질문 의미 보존(#542 국소 평가 chat-02 r0): 메인이 대화 속 목록 질문을 공동 할 일 질문으로 바꿔 넘겨 소통 Agent 가 대화를 찾지 않았다.
    "담당 에이전트에게 넘기는 질문에는 사용자가 찾는 대상·찾는 범위·기간·정보 출처를 바꾸거나 빼지 말고 그대로 담으세요. "
    # 출처 덧붙임 금지(#542 국소 평가 addac7c9 chat-02 r0·r1): 메인이 사용자가 말하지 않은 '공동 할 일 목록'·'일정 탭'을 넘김 질문에 덧붙였다.
    "사용자가 말하지 않은 출처(다른 목록·다른 탭)를 덧붙이지도 마세요. "
    # 할 일 조회의 담당(compound-03): 어느 목록인지 말하지 않은 질문을 한쪽만 확인하면 다른 목록의 할 일을 놓친다. 평가 질문을 예시로 넣지 않는다(`test_main_prompt_todo_routing.py` 가 막는다).
    "할 일 조회는 어느 목록인지에 따라 나눠 부르세요. 가족이 함께 쓰는 목록을 가리키거나 가족 채팅에서 정한 할 일이면 ask_family_chat 만, "
    "내 일정 탭의 일정·할 일을 가리키면 ask_schedule 만 부르세요. 어느 목록인지 말하지 않은 할 일 질문은 ask_family_chat 과 ask_schedule 을 둘 다 불러 "
    "가족 공동 할 일과 일정 탭의 할 일을 모두 확인하세요. "
    # 둘 다 규칙의 범위(addac7c9 chat-02 r0·r1): 가족방 보조 단서(위)와 부딪혀, 방에서 대화 속 목록을 물어도 첫 턴에 두 담당을 함께 불렀다.
    "이렇게 둘 다 부르는 것은 등록된 할 일을 조회할 때뿐이고, 가족 채팅방에서 한 할 일 질문이나 대화에서 이야기한 목록·내용을 묻는 질문에는 쓰지 않습니다. "
    "'오늘'·'이번 주' 같은 말은 기간 조건일 뿐 둘 다 부를지를 정하지 않습니다. "
    "지출 같은 다른 영역을 함께 물으면 그 담당도 부르세요. 할 일을 묻는 조회 요청을 등록·수정 요청으로 바꾸지 마세요. "
    # 자기 가족방과 다른 가족방을 함께 찾아 달라는 혼합 요청: 메인이 질문을 다시 쓰며 '다른 가족방' 조건을 지우면 담당 에이전트가 범위 제한을 밝힐 계기가 없다(isolation-02).
    # 평가 사례의 질문을 예시로 넣지 않는다(평가 질문과 같은 문장이 프롬프트에 있으면 점수가 지침 이해가 아니라 문장 일치를 잰다). `test_gen_isolation_cases.py` 가 막는다.
    "자기 가족방과 다른 가족방(다른 가족)의 대화를 함께 찾아 달라는 요청(혼합 요청)은 직접 거절하지 말고 ask_family_chat 으로 넘기되, "
    "사용자가 말한 검색 범위(다른 가족방까지 포함한다는 조건)와 찾으려는 주제를 지우거나 '이 가족방'으로 바꾸지 말고 한 문장에 그대로 담으세요. "
    "담당 에이전트가 이 가족방만 찾고 다른 가족방은 볼 수 없다고 밝히니 그 답을 그대로 전하세요. "
    "다른 가족방·다른 가족의 정보만 알려 달라는 요청은 찾아볼 우리 가족방 대화가 없으니 도구를 부르지 말고 볼 수 없다고 직접 알려 주세요. "
    "올려 둔 문서·영수증·고지서에 적힌 내용은 채팅이 아니니 search_knowledge 로 찾으세요. "
    "채팅 분석의 일정·할 일은 후보일 뿐 등록된 것이 아니라고 알려 주세요. 사용자가 그 일정 후보를 넣어 달라고 하면('그거 일정에 넣어줘', "
    "'첫 번째 일정 넣어줘') 후보의 날짜·시간·제목·장소를 합친 완전한 문장으로 ask_schedule 에 넘기고, 어느 후보인지 모르겠으면 "
    "어느 것인지 물어보세요. 넣어 달라는 말이 없으면 '일정에 넣어 드릴까요?'라고 먼저 물어보세요. 할 일 후보는 아직 등록하는 길이 없다고 알려 주세요. "
    "사용자가 후보를 가리켜 일정에 넣어 달라고 하면('마지막 거 넣어줘', '토요일 저녁 약속 잡아줘') 다시 확인하지 말고 바로 ask_schedule 로 넘기세요. "
    "날짜가 없는 후보만 날짜를 물어보세요. 일정 여러 개를 한꺼번에 넣어 달라고 하면 한 문장에 몰아 넘기지 말고 일정마다 따로 ask_schedule 을 "
    "부르고, 부른 수와 등록된 수가 같은지 확인한 뒤 모두 알려 주세요. "
    "올려 둔 영수증·고지서로 지출을 등록하거나 정산해 달라고 하면, 또는 '소아과 진료비 정산해줘'처럼 병원·약국·학원 같은 지출을 '영수증'이라는 말 없이 정산·등록해 달라고 해도, 먼저 search_knowledge 로 그 문서가 있는지 찾아 날짜·금액·제목을 읽고, "
    "그 값을 담은 완전한 문장('2026-10-24 치과 128,000원 지출로 등록해줘')을 ask_billing 에 넘기세요. 문서에 나온 날짜를 쓰고 오늘 날짜로 "
    "바꾸지 마세요. 영수증이 둘 이상이라 어느 것인지 모르면 어느 것인지 물어보세요. 정산 내역을 묻는 것이 아니라 영수증을 장부에 올리라는 뜻이면 "
    "조회가 아니라 등록으로 넘기세요. 질문과 관계없는 도구는 함께 부르지 마세요. 장부에 기록된 지출·정산 질문은 ask_billing 으로 확인하세요. 고지서·영수증·명세서·계약서 금액은 search_knowledge 로 찾으세요. 장부인지 문서인지 불분명한 돈 질문은 둘 다 확인하세요. "
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
    db: Session,
    group_id: str,
    user: User,
    name: str,
    args: dict,
    post: Post | None,
    audience: str = "me",
) -> tuple[dict, list[dict], list, list[dict]]:
    """탭 에이전트에게 묻고 (메인에게 줄 결과, 탭 에이전트가 부른 도구 기록, 쓰기 제안, 확인 카드) 를 돌려준다."""
    question = str(args.get("question", "")).strip()
    if not question:
        raise ValueError("question 이 비어 있어요")
    # 일정 에이전트만 어디서 불렀는지(가족방 @가비 = room)를 알아야 한다: 방에서는 공동 일정만 다룬다
    if audience == "direct" and name == "ask_schedule":
        # 1:1 방에서는 일정 에이전트를 아직 쓰지 않는다(상대 한 명 기준 조회·공유는 별도 작업). 개인 일정이 상대에게 보이지 않게 막는다
        return (
            {"answer": "1:1 대화에서는 아직 일정을 다루지 않아요", "can_answer": False},
            [],
            [],
            [],
        )
    extra = {"audience": audience} if name == "ask_schedule" else {}
    ai_guard.note_nested(
        USAGE_FEATURES[name]
    )  # 사용 기록에 어느 탭 에이전트를 썼는지 남긴다(호출 수는 메인 줄에 센다)
    reply = AGENTS[name][1](
        db, group_id, user, question, post, guarded=False, **extra
    )  # 메인 질문의 관문 한 번에 함께 센다
    reply = _without_false_proposal(name, reply)
    result = {"answer": reply.answer, "can_answer": reply.can_answer}
    if reply.user_text:
        result["direct_answer"] = reply.user_text
    if (
        reply.proposals or reply.confirmations
    ):  # 사용자 화면에 확인 버튼이 뜬다. 메인은 등록됐다고 말하면 안 된다
        result["pending_confirmation"] = [p.summary for p in reply.proposals] + [
            c["title"] for c in reply.confirmations
        ]
    return result, reply.tool_calls, reply.proposals, reply.confirmations
