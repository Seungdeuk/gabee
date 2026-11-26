"""관리자 챗봇의 담당(서브 에이전트). `ADMIN_CHATBOT_SUBAGENTS` 가 켜져 있을 때만 쓴다.

메인 챗봇은 숫자 도구와 FAQ 를 직접 갖지 않고, 질문을 담당에게 나눠 묻고 보고를 합쳐 답한다.

    메인 ─┬─ ask_service : 서비스 담당. 회원·가족·참가 요청·문의·AI 사용량·이용 분석 도구(area="service")
          ├─ ask_ops     : 운영 담당. 서버 요청·오류 도구(area="ops")
          └─ ask_rules   : 규칙 담당. 도구 없이 faq.md 만 받는다

담당 하나는 메인과 같은 그래프(`graph.GRAPH`)를 다른 지시·도구로 한 번 더 돌리는 도구다. 메인 쪽에서는 랭체인 도구 하나로 보인다.
- 호출 상한: 메인과 담당이 `Budget` 하나를 나눠 쓴다(질문 하나에 Claude 최대 `TOTAL_MAX_CALLS` 번).
- 실패: 담당의 Claude 호출이 실패하면 "확인할 수 없음" 을 돌려주고 메인은 다른 담당의 보고로 답한다.
- 단계 소식: 담당이 부른 숫자 도구를 "서비스 담당 · 회원 수 확인" 처럼 메인의 tool 소식으로 내보낸다(소식 모양은 그대로).
- 담당에게 가는 질문은 메인이 이미 가린 질문에서 만든 글이다. 숫자 도구의 규칙(개수·비율·시각만)은 그대로다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.llm import client as llm
from app.shared.llm.chat_model import PostChatModel

from .graph import GRAPH, RUN_NAME, Budget, Run, _config, spec
from .live import UNKNOWN, area_tools

FOLDER = Path(__file__).parent
PROMPTS = FOLDER / "prompts"
MAIN_MAX_STEPS = 3  # 메인이 Claude 를 부르는 최대 횟수(마지막 답 포함)
SUB_MAX_STEPS = 3  # 담당 하나가 Claude 를 부르는 최대 횟수
TOTAL_MAX_CALLS = 8  # 질문 하나에 메인과 담당을 합친 최대 호출 수(비용 상한)
# 담당의 Claude 호출이 실패했을 때 나는 예외(service.CALL_ERRORS 와 같다)
CALL_ERRORS = (llm.LLMUnavailable, httpx.HTTPError, ValueError, KeyError)


@dataclass(frozen=True)
class Area:
    name: str  # 메인이 부르는 도구 이름
    label: str  # 답변 단계 화면에 보이는 이름
    description: str  # 메인(Claude)이 읽고 담당을 고른다
    area: str | None  # 숫자 도구 묶음(service | ops). 규칙 담당은 None
    prompt: str  # prompts/ 의 지시 파일


AREAS = (
    Area(
        "ask_service",
        "서비스 담당",
        "회원 수·가입·활성 사용자, 가족 그룹·참가 요청, 문의·신고 건수, AI 사용량, 이용 분석(재방문·퍼널) 같은 "
        "서비스 숫자를 조사해 보고한다. 서비스 숫자가 필요한 질문에 쓴다.",
        "service",
        "service.md",
    ),
    Area(
        "ask_ops",
        "운영 담당",
        "최근 24시간 서버 요청 수·오류율·평균 응답 시간·오류 종류 같은 "
        "서버 상태를 조사해 보고한다. 서버 상태 질문에 쓴다.",
        "ops",
        "ops.md",
    ),
    Area(
        "ask_rules",
        "규칙 담당",
        "가비의 규칙·정책·기능 설명, 관리자 화면 메뉴와 탭 위치, 관리자 설정 방법을 자료에서 찾아 보고한다. "
        "숫자가 아니라 규칙·방법·위치를 묻는 질문에 쓴다.",
        None,
        "rules.md",
    ),
)


class SubQuestion(BaseModel):
    question: str = Field(
        description="이 담당에게 물을 질문 한 문장. 관리자 질문에서 이 담당이 맡을 부분만 적는다"
    )


def _system(area: Area, faq: str) -> str:
    text = (PROMPTS / area.prompt).read_text(encoding="utf-8")
    return text + (f"\n자료:\n{faq}" if area.area is None else "")


def _sub_tool(
    db: Session,
    area: Area,
    post: Callable[[dict], dict],
    max_tokens: int,
    budget: Budget,
    faq: str,
) -> StructuredTool:
    system = _system(area, faq)

    def run(question: str) -> str:
        if budget.left() <= 0:
            return UNKNOWN  # 상한을 다 써서 이 담당은 묻지 못했다
        tool_list = area_tools(db, area.area) if area.area else []
        model = PostChatModel(
            post=post,
            llm_model=settings.llm_model,
            max_tokens=max_tokens,
            system=system,
            tools=[spec(t) for t in tool_list],
        )
        sub = Run(
            model=model,
            tools={t.name: t for t in tool_list},
            max_steps=min(SUB_MAX_STEPS, budget.left()),
            budget=budget,
        )
        write = (
            get_stream_writer()
        )  # 메인 그래프의 단계 소식 통로(스트림이 아니면 아무것도 하지 않는다)
        try:
            for event in GRAPH.stream(
                {"messages": [HumanMessage(content=question)]},
                config=_config(sub, run_name=f"{RUN_NAME}.{area.name}"),
                stream_mode="custom",
            ):
                if (
                    event.get("step") == "tool"
                ):  # 담당의 이해·작성 단계는 메인 단계와 겹쳐 보이지 않게 뺀다
                    write({"step": "tool", "label": f"{area.label} · {event.get('label')}"})
        except CALL_ERRORS:
            return UNKNOWN
        return sub.answer or UNKNOWN

    tool = StructuredTool.from_function(
        func=run, name=area.name, description=area.description, args_schema=SubQuestion
    )
    tool.metadata = {"label": area.label}
    return tool


def build(
    db: Session, post: Callable[[dict], dict], max_tokens: int, budget: Budget, faq: str
) -> list[StructuredTool]:
    """메인 챗봇이 쓸 담당 도구 3개."""
    return [_sub_tool(db, a, post, max_tokens, budget, faq) for a in AREAS]
