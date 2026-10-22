from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db

from . import rag_chat, service
from .models import KnowledgeItem
from .schemas import (
    AskIn,
    AskOut,
    HitOut,
    ItemDetailOut,
    ItemIn,
    ItemOut,
    SearchIn,
    SearchOut,
)

router = APIRouter(
    prefix="/knowledge", tags=["ai-assistant-knowledge"]
)  # ai_assistant 라우터 아래에 붙는다


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(
    body: ItemIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> KnowledgeItem:
    return service.ingest(db, group_id, user.id, **body.model_dump())


@router.get("/items", response_model=list[ItemOut])
def list_items(
    kind_label: str | None = None,
    limit: int = 50,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[KnowledgeItem]:
    return service.list_items(db, group_id, kind_label, min(max(limit, 1), 200))


@router.get("/items/{item_id}", response_model=ItemDetailOut)
def get_item(
    item_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> KnowledgeItem:
    return service.get_item(db, group_id, item_id)


@router.post("/ask", response_model=AskOut)
def ask(
    body: AskIn, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> AskOut:
    """knowledge 시험용 채팅: LLM 이 검색 함수를 불러 기록을 근거로 답한다."""
    r = rag_chat.ask(db, group_id, body.question)
    return AskOut(answer=r.answer, source=r.source, sources=r.sources, tool_calls=r.tool_calls)


@router.post("/search", response_model=SearchOut)
def search(
    body: SearchIn, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> SearchOut:
    hits = service.search(
        db,
        group_id,
        body.query,
        top_k=body.top_k,
        kind_label=body.kind_label,
        date_from=body.date_from,
        date_to=body.date_to,
        include_sensitive=body.include_sensitive,
    )
    return SearchOut(
        hits=[
            HitOut(
                item_id=h.item.id,
                kind_label=h.item.kind_label,
                title=h.item.title,
                snippet=h.chunk.text,
                page_label=h.chunk.page_label,
                score=round(h.score, 4),
                source_path=h.item.source_path,
                occurred_on=h.item.occurred_on,
                has_unread_parts=h.item.has_unread_parts,
                sensitivity=h.item.sensitivity,
            )
            for h in hits
        ]
    )
