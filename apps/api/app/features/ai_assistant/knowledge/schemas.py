from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ItemIn(BaseModel):
    """전처리가 넘기는 기록. 문서는 마크다운 글, 글자 없는 사진은 분류 이름과 경로만 온다."""

    kind_label: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(min_length=1)
    source_path: str | None = Field(default=None, max_length=500)
    occurred_on: date | None = None
    sensitivity: Literal["normal", "sensitive"] | None = None  # 비우면 분류 이름으로 정한다


class ItemUpdateIn(BaseModel):
    """사용자가 확인하며 고친 값. 보낸 칸만 바뀌고, 하나도 안 보내면 "확인했어요"로 처리한다."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    kind_label: str | None = Field(default=None, min_length=1, max_length=100)
    occurred_on: date | None = None
    body_md: str | None = Field(default=None, min_length=1, max_length=50000)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind_label: str
    title: str
    source_path: str | None
    occurred_on: date | None
    has_unread_parts: bool
    sensitivity: str
    created_at: datetime
    needs_review: bool = False  # 읽다 만 부분이 있거나 종류가 애매해서 사용자가 확인해야 하는 기록
    needs_description: bool = False  # 글자가 안 읽힌 사진인데 사용자가 단 설명이 아직 없는 기록
    seen: bool = True  # 요청한 사용자가 읽었거나 직접 올린 기록(본인 것만 알려 준다)


class ItemDetailOut(ItemOut):
    body_md: str


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    kind_label: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    include_sensitive: bool = True


class HitOut(BaseModel):
    item_id: str
    kind_label: str
    title: str
    snippet: str
    page_label: str | None
    score: float
    source_path: str | None
    occurred_on: date | None
    has_unread_parts: bool
    sensitivity: str


class IndexStatusOut(BaseModel):
    """검색 색인 점검(운영자용). 개수와 모델 이름만 있다."""

    current_model: str
    by_model: dict[str, int]
    stale_chunks: int
    stale_items: int
    missing_items: int
    warnings: list[str]


class SearchOut(BaseModel):
    hits: list[HitOut]


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class SourceOut(BaseModel):
    n: int
    item_id: str
    title: str
    kind_label: str
    page: str | None = None
    source_path: str | None = None
    date: str | None = None


class ToolCallOut(BaseModel):
    name: str
    input: dict


class AskOut(BaseModel):
    answer: str
    source: Literal["ai", "fallback"]
    sources: list[SourceOut]
    tool_calls: list[ToolCallOut]


# ---------- 키워드 찾기 (lookup.py) ----------
class FindIn(BaseModel):
    """입력할 때마다 불러도 되는 찾기(LLM·외부 API 를 부르지 않는다)."""

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=30)
    kind_label: str | None = Field(default=None, max_length=100)
    semantic: bool = False  # True 이고 글자 일치가 없을 때만 의미 검색(pgvector)을 쓴다


class FindOut(BaseModel):
    method: Literal["keyword", "semantic"]
    hits: list[HitOut]
