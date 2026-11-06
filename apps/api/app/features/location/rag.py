"""위치 요약 조각의 적재(청킹·임베딩·저장)와 검색. 임베딩은 서버 안에서 계산하고 외부로 보내지 않는다.

- 적재: 구간 → 요약 문장(summary.py) → 임베딩 → location_chunks. 사용자 단위로 통째로 바꾼다.
- 검색: 질문 → 임베딩 → 볼 수 있는 사용자의 조각만 대상으로 코사인 유사도 상위 N개.
권한(누구의 조각을 볼 수 있나)은 부르는 쪽(service)이 user_ids 로 정한다."""

from datetime import datetime

from sqlalchemy.orm import Session

# 문서 지식 검색과 같은 임베더를 쓴다(schedule 이 ai_assistant 의 마스킹을 가져다 쓰는 것과 같은 방식).
from app.features.ai_assistant.knowledge.embedding import TextEmbedder, get_embedder

from . import repository as repo
from .models import LocationChunk
from .summary import ChunkDraft, Span, build_chunks


def index_spans(
    db: Session,
    group_id: str,
    user_ids: dict[str, str],
    spans: list[Span],
    embedder: TextEmbedder | None = None,
) -> int:
    """구간으로 조각을 만들어 저장하고 만든 개수를 돌려준다. user_ids 는 구간의 person_id → 사용자 id.

    커밋은 부르는 쪽이 한다."""
    embedder = embedder or get_embedder()
    drafts: list[ChunkDraft] = build_chunks([s for s in spans if s.person_id in user_ids])
    vectors = embedder.embed_passages([d.text for d in drafts]) if drafts else []
    chunks = [
        LocationChunk(
            user_id=user_ids[d.person_id],
            group_id=group_id,
            kind=d.kind,
            starts_at=d.starts_at,
            ends_at=d.ends_at,
            text=d.text,
            embedding=vec,
            embedding_model=embedder.name,
        )
        for d, vec in zip(drafts, vectors, strict=True)
    ]
    repo.replace_chunks(db, sorted(set(user_ids.values())), chunks)
    return len(chunks)


def _covers(chunk: LocationChunk, at: datetime) -> bool:
    """조각이 시각 at 을 덮는지. SQLite 는 시간대를 저장하지 않아 그때는 시각의 날짜·시각 부분으로 비교한다."""
    if chunk.starts_at.tzinfo is None:
        at = at.replace(tzinfo=None)
    return chunk.starts_at <= at < chunk.ends_at


def search(
    db: Session,
    group_id: str,
    visible_user_ids: list[str],
    question: str,
    limit: int = 10,
    embedder: TextEmbedder | None = None,
    *,
    date_range: tuple[datetime, datetime] | None = None,
    at: datetime | None = None,
    kinds: tuple[str, ...] | None = None,
) -> list[tuple[LocationChunk, float]]:
    """질문과 가까운 조각을 점수 순으로 돌려준다. visible_user_ids 밖 사용자의 조각은 후보에도 오르지 않는다.

    벡터 검색은 날짜·시각 숫자를 잘 구분하지 못해서, 에이전트가 질문에서 뽑은 날짜 범위(date_range)와 시각(at)을 같이 받는다.
    kinds 는 질문의 성격(횟수는 place, 순서는 move·day)에 맞는 조각 종류만 후보로 한다. date_range 와 겹치는 조각만 후보로 하고, at 이 있으면 그 시각을 덮는 조각을 앞에 둔다(그 안에서는 유사도 순).
    시간 값은 PostgreSQL 에서는 시간대가 있는 값으로 넘긴다."""
    embedder = embedder or get_embedder()
    found = repo.search_chunks(
        db,
        group_id,
        visible_user_ids,
        embedder.name,
        embedder.embed_query(question),
        # 시각을 지정하면 그 시각을 덮는 조각을 앞으로 올리려고 후보를 넉넉히 가져온다
        limit if at is None else max(limit, 200),
        date_range,
        kinds,
    )
    if at is not None:
        found.sort(
            key=lambda row: not _covers(row[0], at)
        )  # 정렬은 안정적이라 유사도 순서가 유지된다
        found = found[:limit]
    return found
