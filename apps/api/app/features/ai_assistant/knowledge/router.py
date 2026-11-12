from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.shared.auth import current_group_id, current_user, require_operator
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.errors import bad_request, not_found

from .. import family_names, files
from .. import repository as photo_repo
from . import embedding, from_ingest, index_health, lookup, rag_chat, service
from .models import KnowledgeItem
from .schemas import (
    AskIn,
    AskOut,
    FindIn,
    FindOut,
    HitOut,
    IndexStatusOut,
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
    # source_path 는 서버가 만든 원본 참조만 쓴다. 클라이언트가 보낸 값은 무시한다(남의 원본을 가리켜 지우게 하는 것을 막기 위해).
    return service.ingest(db, group_id, user.id, **body.model_dump(exclude={"source_path"}))


@router.get("/items", response_model=list[ItemOut])
def list_items(
    kind_label: str | None = None,
    limit: int = 50,
    created_from: date | None = None,
    created_to: date | None = None,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> list[ItemOut]:
    """created_from·created_to 는 설정된 날짜 경계(`ai_day_utc_offset_hours`, 기본 한국 시간 KST)의 달력 날짜이고 양끝을 포함한다(created_at 기준)."""
    try:
        start, end = service.created_bounds(
            created_from, created_to, settings.ai_day_utc_offset_hours
        )
    except ValueError as exc:
        raise bad_request("invalid_range", str(exc)) from exc
    items = service.list_items(db, group_id, kind_label, min(max(limit, 1), 200), start, end)
    return _show(db, group_id, service.attach_seen(db, user.id, items), ItemOut)


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
    item_id: str,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ItemDetailOut:
    """기록을 열면 이 사용자의 읽음이 남는다(다른 가족 기록이면 404 이고 남기지 않는다)."""
    item = service.get_item(db, group_id, item_id)
    service.mark_read(db, item.id, user.id)
    item.seen = True
    return _show(db, group_id, [item], ItemDetailOut)[0]


@router.patch("/items/{item_id}", response_model=ItemDetailOut)
def update_item(
    item_id: str,
    body: ItemUpdateIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> ItemDetailOut:
    """확인하며 고친 값으로 기록을 바꾼다. 가족 그룹이 다르면 없는 기록처럼 404 다."""
    item = service.update_item(db, group_id, item_id, body.model_dump(exclude_unset=True))
    photo_repo.set_status(db, item.id, "analyzed")  # 올린 파일이면 확인 필요 표시를 끈다
    return _show(db, group_id, service.attach_seen(db, user.id, [item]), ItemDetailOut)[0]


@router.post("/ask", response_model=AskOut)
def ask(
    body: AskIn,
    user=Depends(current_user),
    group_id: str = Depends(current_group_id),
    db: Session = Depends(get_db),
) -> AskOut:
    """knowledge 시험용 채팅: LLM 이 검색 함수를 불러 기록을 근거로 답한다(가족 AI 동의·쿨다운·하루 한도 가드를 거친다)."""
    r = rag_chat.ask_guarded(db, user.id, group_id, body.question, feature="knowledge_ask")
    return AskOut(answer=r.answer, source=r.source, sources=r.sources, tool_calls=r.tool_calls)


@router.get("/index-status", response_model=IndexStatusOut)
def index_status(
    _: object = Depends(require_operator("admin")), db: Session = Depends(get_db)
) -> IndexStatusOut:
    """검색 색인 점검(운영자 전용, 읽기 전용): 서버가 쓰는 임베딩 모델 이름과 DB 조각의 모델별 개수.
    이름이 어긋나면 문서가 오류 없이 의미 검색에서 빠지므로 개수와 경고만 알려 준다(내용·가족 그룹 id 는 싣지 않는다)."""
    report = index_health.collect(db, embedding.expected_model_name())
    return IndexStatusOut(
        **report, warnings=index_health.warnings(db.get_bind().dialect.name, report)
    )


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
    out = [
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
    return SearchOut(hits=_show_hits(db, group_id, out))


@router.post("/find", response_model=FindOut)
def find(
    body: FindIn, group_id: str = Depends(current_group_id), db: Session = Depends(get_db)
) -> FindOut:
    """글자 일치 찾기(LLM 호출 없음). 없고 semantic=true 일 때만 의미 검색."""
    found = lookup.find(
        db,
        group_id,
        body.query,
        limit=body.limit,
        kind_label=body.kind_label,
        semantic=body.semantic,
    )
    return FindOut(method=found.method, hits=_show_hits(db, group_id, found.hits))


def _mark_review(db: Session, group_id: str, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
    """응답에 needs_review 를 채운다(올린 파일이 확인 필요 상태이거나 읽지 못한 부분이 있는 기록)."""
    waiting = photo_repo.review_ids(db, group_id)
    for item in items:
        item.needs_review = item.id in waiting or item.has_unread_parts
        item.needs_description = from_ingest.needs_description(item.kind_label, item.body_md)
    return items


def _names(db: Session, group_id: str) -> dict[str, str]:
    return family_names.shown_names(family_names.load_members(db, group_id))


def _show(db: Session, group_id: str, items: list[KnowledgeItem], model: type) -> list:
    """응답 모델로 만들면서 글 속 `[가족:<id>]` 를 현재 이름으로 되돌린다.
    DB 객체(item)의 글은 건드리지 않는다: 되돌린 글이 세션에 남아 저장되면 안 된다."""
    names = _names(db, group_id)
    out = []
    for item in _mark_review(db, group_id, items):
        view = model.model_validate(item)
        view.title = family_names.restore(view.title, names)
        if hasattr(view, "body_md"):
            view.body_md = family_names.restore(view.body_md, names)
        out.append(view)
    return out


def _show_hits(db: Session, group_id: str, hits: list[HitOut]) -> list[HitOut]:
    names = _names(db, group_id)
    return [
        h.model_copy(
            update={
                "title": family_names.restore(h.title, names),
                "snippet": family_names.restore(h.snippet, names),
            }
        )
        for h in hits
    ]
