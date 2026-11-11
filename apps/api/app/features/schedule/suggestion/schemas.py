"""데일리 체크 추천 문구 응답 모양. 읽기 전용이라 요청 본문은 없다."""

from pydantic import BaseModel


class HabitSuggestionOut(BaseModel):
    """추천 습관 하나. 앱의 '습관 추가' 입력 값으로 그대로 쓴다(kind 1 이면 goal·unit 은 비어 있다)."""

    name: str
    kind: int  # 1 한 번 체크 · 2 횟수 세기
    goal: int | None = None
    unit: str | None = None


class CheerSuggestionOut(BaseModel):
    """추천 응원 문구 하나."""

    message: str
