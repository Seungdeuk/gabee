"""전화 이야깃거리 응답 모양. 요청 본문은 없다."""

from typing import Literal

from pydantic import BaseModel


class CallTalkPoint(BaseModel):
    say: str  # 굵은 첫 줄(AI 문구) 또는 안부 문장
    ask: str  # 아랫줄. 안부 문구는 빈 문자열


class CallTalkOut(BaseModel):
    source: Literal["ai", "greeting"]
    reason: Literal["", "no_habits", "limit", "no_consent", "error"]
    points: list[CallTalkPoint]
