from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.shared.errors import ApiError, not_found

from ..ingest import masking
from . import repository as repo
from .chunking import DOUBT_MARK, UNREAD_MARK, split_markdown
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
    item_id: str | None = None,
) -> KnowledgeItem:
    """전처리가 넘긴 기록 한 건을 조각내고 임베딩해서 저장한다."""
    embedder = _embedder(db)
    item = KnowledgeItem(
        **({"id": item_id} if item_id else {}),
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
    return repo.add_item(db, item, _chunks(embedder, group_id, body_md))


def _chunks(embedder: TextEmbedder, group_id: str, body_md: str) -> list[KnowledgeChunk]:
    pieces = split_markdown(body_md)
    vectors = embedder.embed_passages([p.text for p in pieces])
    return [
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


def update_item(db: Session, group_id: str, item_id: str, changes: dict) -> KnowledgeItem:
    """사용자가 확인하며 고친 값으로 기록을 바꾸고 검색용 조각을 다시 만든다.

    changes 에는 고친 칸만 있다(title, kind_label, occurred_on, body_md). 비어 있으면 고치지 않고 "확인했다"는 뜻이다.
    글은 다시 개인정보 가리기를 거치고, 읽지 못한 부분 표시는 사용자가 확인했으므로 지운다."""
    item = get_item(db, group_id, item_id)
    embedder = _embedder(db)
    title = changes.get("title") or item.title
    kind = changes.get("kind_label") or item.kind_label
    body = changes.get("body_md") or item.body_md
    body = masking.mask_text(body, masking.sensitive_kind(body))
    lines = [
        ln.removesuffix(DOUBT_MARK).rstrip()  # 사용자가 확인했으니 [불확실] 표시는 지운다
        for ln in body.split("\n")
        if ln.strip() != UNREAD_MARK
    ]
    if lines and lines[0].startswith("# "):  # 제목·분류 줄은 고친 값과 맞춘다
        lines[0] = f"# {title}"
    if len(lines) > 1 and lines[1].startswith("분류:"):
        lines[1] = f"분류: {kind}"
    body = "\n".join(lines).strip()
    if not body:
        raise ApiError(422, "empty_body", "내용이 비어 있어요")
    sensitive = (
        item.sensitivity == "sensitive"
        or masking.sensitive_kind(body) != "none"
        or _sensitivity(kind, None) == "sensitive"
    )
    item.title, item.kind_label, item.body_md = title, kind, body
    if "occurred_on" in changes:
        item.occurred_on = changes["occurred_on"]
    item.has_unread_parts = False
    item.sensitivity = "sensitive" if sensitive else "normal"
    return repo.replace_chunks(db, item, _chunks(embedder, group_id, body))


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
