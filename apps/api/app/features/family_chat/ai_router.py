"""가족 채팅 AI 기능 엔드포인트. family_chat 라우터에 포함되어 /family-chat/ai 아래로 열린다.

모든 호출은 가족 그룹의 AI 동의, 결과 캐시, 쿨다운·하루 한도, 동시 실행 제한(app/shared/ai_guard.py)을 거친다.
일반 메시지 전송(POST /family-chat/messages)은 AI 를 부르지 않는다."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import ai_service
from .ai_schemas import (
    AiSettingsIn,
    AiSettingsOut,
    AnalysisOut,
    PreviewOut,
    RangeIn,
    RepliesOut,
    TopicsOut,
)

router = APIRouter(prefix="/ai")


@router.get("/settings", response_model=AiSettingsOut)
def get_settings(
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AiSettingsOut:
    """우리 가족의 AI 사용 동의 여부, 한도, 오늘 사용량."""
    return ai_service.get_settings(db, user, group_id)


@router.put("/settings", response_model=AiSettingsOut)
def put_settings(
    body: AiSettingsIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AiSettingsOut:
    """가족 소유자·관리자가 AI 기능 사용에 동의(켜기)하거나 끈다. 꺼져 있으면 AI 요청은 403 ai_not_enabled."""
    return ai_service.set_enabled(db, user, group_id, body.enabled)


@router.post("/preview", response_model=PreviewOut)
def preview(
    body: RangeIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> PreviewOut:
    """분석 요청과 같은 범위에서 AI 가 실제로 받게 될 가명화된 대화를 미리 보여 준다. AI 를 부르지 않고 한도도 쓰지 않는다(동의와 무관, 사용자당 분당 20회)."""
    return ai_service.preview(db, user, group_id, body)


@router.post("/analysis", response_model=AnalysisOut)
def analyze(
    body: RangeIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AnalysisOut:
    """최근 대화를 한 번의 AI 호출로 분석한다: 요약·중요 메시지·일정 후보·할 일 후보(구조화 출력). 일정·할 일은 후보일 뿐 사용자가 확인해야 등록된다."""
    return ai_service.analysis(db, user, group_id, body)


@router.post("/replies", response_model=RepliesOut)
def replies(
    body: RangeIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> RepliesOut:
    """마지막 메시지에 이어 보낼 답장 후보(요청할 때만)."""
    return ai_service.reply_suggestions(db, user, group_id, body)


@router.post("/topics", response_model=TopicsOut)
def topics(
    body: RangeIn,
    user: User = Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> TopicsOut:
    """이어갈 대화 주제 추천(요청할 때만)."""
    return ai_service.topic_suggestions(db, user, group_id, body)
