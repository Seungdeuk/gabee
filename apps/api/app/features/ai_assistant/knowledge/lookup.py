"""@가비 문서 찾기(글자 일치 → 없으면 의미 검색). LLM 을 부르지 않는다.

- 같은 가족 그룹 기록의 제목·본문 조각에서 대소문자 무시 부분 일치로 먼저 찾고, 결과가 없고 semantic=True 일 때만
  기존 의미 검색(service.search, 로컬 임베딩)을 쓴다. 입력할 때마다 불러도 비용이 없다.
- 문서 요약·질문 답변은 메인 에이전트(`/ai-assistant/chat`)가 기록 검색과 `get_item` 으로 직접 하므로 따로 모델을 부르는 길을 두지 않는다.
- 가족 그룹은 항상 호출한 쪽이 current_group_id 로 정해 넘긴다.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.errors import ApiError, bad_request

from .. import family_names
from . import service, tools
from .models import KnowledgeChunk, KnowledgeItem
from .schemas import FindHitOut, FindOut


@dataclass(frozen=True)
class Found:
    item: KnowledgeItem
    chunk: KnowledgeChunk
    score: float


def _like_pattern(term: str) -> str:
    """LIKE 특수문자(% _ \\)를 이스케이프한 부분 일치 패턴."""
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def keyword_chunks(
    db: Session,
    group_id: str,
    terms: list[str],
    *,
    kind_label: str | None = None,
    item_ids: list[str] | None = None,
    include_sensitive: bool = True,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    created_by: list[str] | None = None,
) -> list[Found]:
    """낱말이 제목·조각 글에 들어 있는 조각을 기록마다 하나씩, 많이 맞은 순으로 돌려준다(PostgreSQL·SQLite 공통)."""
    terms = [t for t in terms if t]
    if not terms:
        return []
    conds = []
    for t in terms:
        pat = _like_pattern(t)
        conds.append(func.lower(KnowledgeChunk.text).like(pat, escape="\\"))
        conds.append(func.lower(KnowledgeItem.title).like(pat, escape="\\"))
    q = (
        select(KnowledgeChunk, KnowledgeItem)
        .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.item_id)
        .where(
            KnowledgeChunk.group_id == group_id,
            KnowledgeItem.group_id == group_id,
            or_(*conds),
        )
    )
    if kind_label:
        q = q.where(KnowledgeItem.kind_label == kind_label)
    if item_ids is not None:
        q = q.where(KnowledgeItem.id.in_(item_ids))
    if not include_sensitive:
        q = q.where(KnowledgeItem.sensitivity != "sensitive")
    if created_from is not None:
        q = q.where(KnowledgeItem.created_at >= created_from)  # 올린 날(UTC 경계, 시작 이상)
    if created_to is not None:
        q = q.where(KnowledgeItem.created_at < created_to)  # (끝 미만)
    if created_by is not None:
        q = q.where(KnowledgeItem.created_by.in_(created_by))  # 올린 사람
    q = q.order_by(KnowledgeItem.occurred_on.desc(), KnowledgeItem.created_at.desc()).limit(500)
    lowered = [t.lower() for t in terms]
    best: dict[str, Found] = {}
    for chunk, item in db.execute(q).all():
        hay = f"{item.title}\n{chunk.text}".lower()
        score = sum(1 for t in lowered if t in hay) / len(lowered)
        cur = best.get(item.id)
        if cur is None or score > cur.score:
            best[item.id] = Found(item, chunk, score)
    return sorted(best.values(), key=lambda f: f.score, reverse=True)


def _hit(
    item: KnowledgeItem, chunk: KnowledgeChunk, score: float, names: dict[str, str]
) -> FindHitOut:
    return FindHitOut(
        item_id=item.id,
        kind_label=item.kind_label,
        title=item.title,
        snippet=chunk.text,
        page_label=chunk.page_label,
        score=round(score, 4),
        source_path=item.source_path,
        occurred_on=item.occurred_on,
        has_unread_parts=item.has_unread_parts,
        sensitivity=item.sensitivity,
        # 올린 날(한국 날짜)·올린 사람·원본 채팅 사진 id: AI 도구 결과(#393)와 같은 계산
        **tools._upload_info(item, names),
    )


def _uploaded_filter(
    members: list,
    uploaded_from: date | None,
    uploaded_to: date | None,
    uploaded_by: str | None,
) -> tuple[datetime | None, datetime | None, list[str] | None]:
    """올린 날(한국 날짜, 양끝 포함)·올린 사람 조건을 (시작 이상 UTC, 끝 미만 UTC, 올린 사람 user_id 들)로 바꾼다.

    AI 도구(#393)처럼 조건을 조용히 무시하지 않는다: 범위가 틀리면 400, 이 가족에서 이름을 찾지 못하면 422 다.
    같은 이름이 여럿이면 모두 합쳐 찾는다(결과의 uploaded_by 로 구분된다). 빈 글자는 조건 없음으로 본다."""
    try:
        start, end = service.created_bounds(
            uploaded_from, uploaded_to, settings.ai_day_utc_offset_hours
        )
    except ValueError as exc:
        raise bad_request("invalid_range", str(exc)) from exc
    if not (uploaded_by and uploaded_by.strip()):
        return start, end, None
    ids = family_names.match_member(members, uploaded_by)
    if not ids:
        near = family_names.suggest_members(members, uploaded_by)
        hint = f" 비슷한 이름의 가족: {', '.join(near)}." if near else ""
        raise ApiError(
            422,
            "unknown_uploader",
            f"'{uploaded_by.strip()}' 이름의 올린 사람(가족 구성원)을 찾지 못했어요." + hint,
        )
    return start, end, ids


def find(
    db: Session,
    group_id: str,
    query: str,
    *,
    limit: int = 10,
    kind_label: str | None = None,
    semantic: bool = False,
    uploaded_from: date | None = None,
    uploaded_to: date | None = None,
    uploaded_by: str | None = None,
) -> FindOut:
    """글자 일치로 먼저 찾고, 없고 semantic 일 때만 의미 검색. LLM 은 부르지 않는다.
    올린 날·올린 사람 조건은 글자 일치와 의미 검색 모두에 똑같이 건다."""
    query = query.strip()
    if not query:
        raise ApiError(422, "empty_query", "검색어를 입력해 주세요")
    members = family_names.load_members(db, group_id)
    names = family_names.shown_names(members)
    start, end, uploaders = _uploaded_filter(members, uploaded_from, uploaded_to, uploaded_by)
    found = keyword_chunks(
        db,
        group_id,
        [query],
        kind_label=kind_label,
        created_from=start,
        created_to=end,
        created_by=uploaders,
    )
    if found:
        return FindOut(
            method="keyword", hits=[_hit(f.item, f.chunk, 1.0, names) for f in found[:limit]]
        )
    if not semantic:
        return FindOut(method="keyword", hits=[])
    hits = service.search(
        db,
        group_id,
        query,
        top_k=limit,
        kind_label=kind_label,
        created_from=start,
        created_to=end,
        created_by=uploaders,
    )
    return FindOut(method="semantic", hits=[_hit(h.item, h.chunk, h.score, names) for h in hits])
