"""일정 에이전트 진입점. 메인 오케스트레이터(개인·가족 채팅)가 부르고, 그 전에는 일정 라우터가 부른다.

지금은 뼈대: 요청 종류를 가르고 읽을 데이터를 정하는 데까지만 한다. 종류별 처리(질의·추천·등록·수정·삭제·체크)는
다음 단계에서 채운다. 일정 요청이 아니면 `not_schedule` 로 돌려줘 메인이 직접 답하게 한다.
"""

from sqlalchemy.orm import Session

from app.shared.auth import ensure_group_member

from . import intent as intent_mod
from . import reader
from .schemas import AgentRequest, AgentResponse


def handle(db: Session, user_id: str, group_id: str, request: AgentRequest) -> AgentResponse:
    ensure_group_member(db, user_id, group_id)  # 라우터 밖에서 service 를 부르므로 직접 확인한다
    kind = intent_mod.classify(db, user_id, group_id, request.text)
    if kind == "not_schedule":
        return AgentResponse(intent=kind)
    reader.read(db, group_id, request.channel)
    return AgentResponse(intent=kind, text="아직 이 요청은 처리할 수 없어요")
