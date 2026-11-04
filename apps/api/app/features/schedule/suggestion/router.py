"""데일리 체크 추천 문구 API(읽기 전용). `check_router.py` 에서 `/schedule/check/suggestions` 아래로 붙는다.

- LLM 을 부르지 않고 DB(`events_check_suggestions`)에서 무작위로 골라 준다. 새로고침 같은 별도 동작은 없다.
- 로그인과 현재 가족 그룹이 필요하다. 사람·가족과 무관한 공용 목록이다.
- 추천이 모자라거나 비어도 오류가 아니다(빈 목록). 앱이 내장 목록으로 채운다.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from ..constants import SUGGEST_CHEER, SUGGEST_HABIT
from . import repository
from .schemas import CheerSuggestionOut, HabitSuggestionOut

router = APIRouter(prefix="/suggestions")

HABIT_COUNT = 3  # 습관 추가 화면에 보이는 추천 수
CHEER_COUNT = 2  # 응원 보내기 시트에 보이는 문구 수


@router.get("/habits", response_model=list[HabitSuggestionOut])
def habit_suggestions(
    exclude: list[str] = Query(
        default=[], max_length=100, description="이미 내 목록에 있는 습관 이름(빼고 고른다)"
    ),
    limit: int = Query(default=HABIT_COUNT, ge=1, le=10),
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """추천 습관 무작위 limit 개(기본 3). exclude 에 보낸 이름은 제외한다."""
    rows = repository.random_active(db, SUGGEST_HABIT, limit, exclude)
    return [{"name": r.content, "kind": r.kind, "goal": r.goal, "unit": r.unit} for r in rows]


@router.get("/cheers", response_model=list[CheerSuggestionOut])
def cheer_suggestions(
    limit: int = Query(default=CHEER_COUNT, ge=1, le=10),
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """추천 응원 문구 무작위 limit 개(기본 2)."""
    rows = repository.random_active(db, SUGGEST_CHEER, limit)
    return [{"message": r.content} for r in rows]
