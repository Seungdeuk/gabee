from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user
from app.shared.db import get_db
from app.shared.errors import not_found

from .. import files
from .. import repository as photo_repo
from . import from_ingest, rag_chat, service
from .models import KnowledgeItem
from .schemas import (
    AskIn,
    AskOut,
    HitOut,
    ItemDetailOut,
    ItemIn,
    ItemOut,
    ItemUpdateIn,
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
    items = service.list_items(db, group_id, kind_label, min(max(limit, 1), 200))
    return _mark_review(db, group_id, items)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> Response:
    """기록과 원본 파일을 지운다(되돌릴 수 없음). 가족 그룹이 다르면 없는 기록처럼 404 다."""
    if not files.delete_record(db, group_id, item_id):
        raise not_found("기록")
    return Response(status_code=204)


@router.get("/items/{item_id}", response_model=ItemDetailOut)
def get_item(
    item_id: str, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> KnowledgeItem:
    return _mark_review(db, group_id, [service.get_item(db, group_id, item_id)])[0]


@router.patch("/items/{item_id}", response_model=ItemDetailOut)
def update_item(
    item_id: str,
    body: ItemUpdateIn,
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> KnowledgeItem:
    """확인하며 고친 값으로 기록을 바꾼다. 가족 그룹이 다르면 없는 기록처럼 404 다."""
    item = service.update_item(db, group_id, item_id, body.model_dump(exclude_unset=True))
    photo_repo.set_status(db, item.id, "analyzed")  # 올린 파일이면 확인 필요 표시를 끈다
    return _mark_review(db, group_id, [item])[0]


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


def _mark_review(db: Session, group_id: str, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
    """응답에 needs_review 를 채운다(올린 파일이 확인 필요 상태이거나 읽지 못한 부분이 있는 기록)."""
    waiting = photo_repo.review_ids(db, group_id)
    for item in items:
        item.needs_review = item.id in waiting or item.has_unread_parts
        item.needs_description = from_ingest.needs_description(item.kind_label, item.body_md)
    return items
