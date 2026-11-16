"""통합관리자 챗봇 에이전트. Claude 가 각 기능이 올린 도구 중 필요한 숫자를 골라 읽고 답한다(임베딩·검색 없음).

도구를 부르며 답하는 반복은 `graph.py`(랭그래프)가 하고, 모델은 랭체인 모델(`PostChatModel`), 도구는 랭체인 도구(`live.tools`)다.
Claude 는 가비의 규칙을 모르므로 answer_format.md(답 형식)와 faq.md(규칙)를 지시로 함께 준다. 일상 질문 거절도 Claude 가 한다.
팀 문서를 넣는 곳은 faq.md 하나이고, 가족 데이터는 다루지 않는다."""

import logging
from datetime import datetime
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm import client as llm
from app.shared.llm import transport
from app.shared.llm.chat_model import PostChatModel

from .graph import Run, run_chat, spec
from .live import tools
from .schemas import AdminAskOut

log = logging.getLogger(__name__)
ASK_MAX_TOKENS = 2000
ASK_MAX_STEPS = 4  # Claude 를 부르는 최대 횟수(마지막 답 포함). 비용을 막는다
FOLDER = Path(__file__).parent
FAQ = (FOLDER / "faq.md").read_text(encoding="utf-8")
# 말투와 답 모양은 answer_format.md, 가비 규칙은 faq.md 에서 고친다. 서버가 켜질 때 읽는다
ASK_SYSTEM = (FOLDER / "answer_format.md").read_text(encoding="utf-8") + f"\n자료:\n{FAQ}"


def _post(body: dict) -> dict:
    """Claude 호출: 429·5xx·연결 실패는 한 번 더 시도한다(시험은 이 이름을 가짜로 바꾼다)."""
    return transport.post_messages(body, timeout=60.0, retry=True)


def _answer(db: Session, question: str) -> str:
    tool_list = tools(db)
    model = PostChatModel(
        post=_post,
        llm_model=settings.llm_model,
        max_tokens=ASK_MAX_TOKENS,
        system=ASK_SYSTEM,
        tools=[spec(t) for t in tool_list],
    )
    run = Run(model=model, tools={t.name: t for t in tool_list}, max_steps=ASK_MAX_STEPS)
    run_chat(run, [HumanMessage(content=mask_text(question))])
    if not run.answer:
        raise llm.LLMUnavailable("AI 가 정해진 횟수 안에 답을 끝내지 못했어요")
    return run.answer


def ask(db: Session, user_id: str, question: str, now: datetime | None = None) -> AdminAskOut:
    """키가 없으면 503 ai_key_missing, 호출이 실패하면 503 llm_failed. 하루 한도는 두지 않는다(2026-11-09 결정)."""
    if not llm.available():
        raise ApiError(503, "ai_key_missing", "AI 키가 아직 설정되지 않았어요")
    try:
        answer = _answer(db, question)
    except (llm.LLMUnavailable, httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("관리자 챗봇 호출 실패: %s", e)  # 오류 종류만 있고 질문·키는 없다
        raise ApiError(
            503, "llm_failed", "AI 가 지금 답하지 못했어요. 잠시 뒤 다시 해 주세요"
        ) from None
    return AdminAskOut(answer=answer)
