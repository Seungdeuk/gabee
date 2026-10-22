from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.shared.errors import ApiError, not_found

from . import repository as repo
from .chunking import UNREAD_MARK, split_markdown
from .embedding import TextEmbedder, get_embedder
from .models import EMBED_DIM, KnowledgeChunk, KnowledgeItem

# 분류 이름에 이 낱말이 들어 있으면 민감 기록으로 다룬다(전처리가 sensitivity 를 직접 주면 그 값이 우선).
SENSITIVE_WORDS = (
    "가족관계",
    "주민등록",
    "여권",
    "운전면허",
    "신분증",
    "이력서",
    "병원",
    "진료",
    "처방",
    "건강검진",
    "퇴원",
    "인물",
)


@dataclass(frozen=True)
class Hit:
    item: KnowledgeItem
    chunk: KnowledgeChunk
    score: float


def _embedder(db: Session) -> TextEmbedder:
    """PostgreSQL 의 vector 칸은 길이가 고정이라, 모델 파일이 없어 다른 길이의 임베더가 잡히면 저장·검색을 막는다."""
    embedder = get_embedder()
    if db.get_bind().dialect.name == "postgresql" and embedder.dim != EMBED_DIM:
        raise ApiError(
            503,
            "embedding_model_missing",
            f"임베딩 모델을 찾지 못했어요(필요한 벡터 길이 {EMBED_DIM}). EMBED_MODEL_DIR 를 확인해 주세요",
        )
    return embedder


def _sensitivity(kind_label: str, given: str | None) -> str:
    if given:
        return given
    return "sensitive" if any(w in kind_label for w in SENSITIVE_WORDS) else "normal"


def ingest(
    db: Session,
    group_id: str,
    user_id: str,
    *,
    kind_label: str,
    title: str,
    body_md: str,
    source_path: str | None = None,
    occurred_on: date | None = None,
    sensitivity: str | None = None,
) -> KnowledgeItem:
    """전처리가 넘긴 기록 한 건을 조각내고 임베딩해서 저장한다."""
    embedder = _embedder(db)
    pieces = split_markdown(body_md)
    vectors = embedder.embed_passages([p.text for p in pieces])
    item = KnowledgeItem(
        group_id=group_id,
        created_by=user_id,
        kind_label=kind_label,
        title=title,
        body_md=body_md,
        source_path=source_path,
        occurred_on=occurred_on,
        has_unread_parts=UNREAD_MARK in body_md,
        sensitivity=_sensitivity(kind_label, sensitivity),
    )
    chunks = [
        KnowledgeChunk(
            group_id=group_id,
            seq=p.seq,
            page_label=p.page_label,
            text=p.text,
            embedding=v,
            embedding_model=embedder.name,
        )
        for p, v in zip(pieces, vectors, strict=True)
    ]
    return repo.add_item(db, item, chunks)


def search(
    db: Session,
    group_id: str,
    query: str,
    *,
    top_k: int = 5,
    kind_label: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_sensitive: bool = True,
) -> list[Hit]:
    """질문과 가장 가까운 기록을 점수 순으로 돌려준다(기록마다 가장 가까운 조각 하나)."""
    embedder = _embedder(db)
    rows = repo.search_chunks(
        db,
        group_id,
        embedder.name,
        embedder.embed_query(query),
        kind_label,
        date_from,
        date_to,
        include_sensitive,
    )
    best: dict[str, Hit] = {}
    for chunk, item, score in rows:  # 점수 순이라 기록마다 처음 나온 조각이 가장 가깝다
        best.setdefault(item.id, Hit(item=item, chunk=chunk, score=score))
    return sorted(best.values(), key=lambda h: h.score, reverse=True)[:top_k]


def get_item(db: Session, group_id: str, item_id: str) -> KnowledgeItem:
    item = repo.get_item(db, group_id, item_id)
    if item is None:
        raise not_found("기록")
    return item


def list_items(
    db: Session, group_id: str, kind_label: str | None = None, limit: int = 50
) -> list[KnowledgeItem]:
    return repo.list_items(db, group_id, kind_label, limit)


def reindex(db: Session, group_id: str | None = None) -> int:
    """다른 모델로 만든 벡터를 지금 모델로 다시 만든다. 모델을 바꾼 뒤에 한 번 부른다."""
    embedder = _embedder(db)
    stale = repo.stale_chunks(db, embedder.name, group_id)
    for chunk, vec in zip(stale, embedder.embed_passages([c.text for c in stale]), strict=True):
        chunk.embedding = vec
        chunk.embedding_model = embedder.name
    db.commit()
    return len(stale)
