from typing import Literal

from pydantic import BaseModel, Field


class AdminAskIn(BaseModel):
    q: str = Field(min_length=2, max_length=300)


class AdminAskOut(BaseModel):
    answer: str


AdminAskStep = Literal["received", "masked", "understand", "tool", "write", "answer", "error"]


class AdminAskEvent(BaseModel):
    """`POST /admin/knowledge/ask/stream` 이 `data: ` 줄마다 보내는 단계 소식.

    received 질문 확인 · masked 개인정보 가림 · understand 질문 이해(Claude 첫 호출) · tool 숫자 조회(label 은 화면용 도구 이름)
    · write 답 작성 · answer 끝(answer 에 답) · error 실패(code, message). 질문 글과 도구가 읽은 숫자는 보내지 않는다."""

    step: AdminAskStep
    label: str | None = None
    answer: str | None = None
    code: str | None = None
    message: str | None = None
