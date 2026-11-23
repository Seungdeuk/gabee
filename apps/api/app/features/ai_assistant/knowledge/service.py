from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.errors import ApiError, not_found

from .. import family_names
from ..ingest import masking
from . import hybrid as hybrid_search
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


# 가족방 채팅 문서에서만 민감 표시를 더 붙이는 이름(신분·금융·의료). 기존 업로드의 민감 판단(SENSITIVE_WORDS)은 바꾸지 않는다.
CHAT_EXTRA_SENSITIVE_WORDS = ("외국인등록", "통장", "진단", "소견", "검사결과")


@dataclass(frozen=True)
class Hit:
    item: KnowledgeItem
    chunk: KnowledgeChunk
    score: float
    # 같은 기록의 다음으로 가까운 조각(per_item > 1 일 때만), 점수 순
    more: tuple[KnowledgeChunk, ...] = ()


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


def is_sensitive(kind_label: str, given: str | None = None, *, strict: bool = False) -> bool:
    """이 분류(또는 전처리가 준 값)가 민감 기록인지. strict 는 가족방 채팅 문서용으로, 신분·금융·의료 이름도 민감으로 본다(등록은 하되 민감 표시를 붙인다)."""
    if _sensitivity(kind_label, given) == "sensitive":
        return True
    return strict and any(w in kind_label for w in CHAT_EXTRA_SENSITIVE_WORDS)


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
    source_attachment_id: str | None = None,
) -> KnowledgeItem:
    """전처리가 넘긴 기록 한 건을 조각내고 임베딩해서 저장한다. source_attachment_id 는 채팅 첨부에서 자동 등록할 때만 준다."""
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
        source_attachment_id=source_attachment_id,
        family_user_ids=family_names.extract_ids(title, body_md) or None,
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
    # 앱은 되돌린 이름을 보여 주므로 사용자가 고친 글에는 실명이 들어 있다 -> 가리기 전에 다시 자리표시로 바꾼다.
    # 이미 저장된 글(자리표시가 있다)도 같은 길을 지나게 해서 user_id 숫자 덩어리가 번호로 오인되지 않게 한다.
    tagger = family_names.FamilyTagger(family_names.load_members(db, group_id))
    title = tagger.tag(title)
    body = tagger.protect(changes.get("body_md") or item.body_md)
    privacy_kind = masking.sensitive_kind(body)
    if (
        privacy_kind == "bankbook"
        and item.sensitivity != "sensitive"
        and masking.is_account_notice(body)
    ):
        privacy_kind = "none"  # 이미 일반 문서로 등록된 납부 계좌 안내문: 확인·수정해도 다시 민감 문서로 바뀌지 않는다
    body = tagger.expand(masking.mask_text(body, privacy_kind))
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
        or privacy_kind != "none"
        or _sensitivity(kind, None) == "sensitive"
    )
    item.title, item.kind_label, item.body_md = title, kind, body
    item.family_user_ids = family_names.extract_ids(title, body) or None
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
    family_user_ids: list[str] | None = None,
    per_item: int = 1,
    hybrid: bool | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    created_by: list[str] | None = None,
    chat_verified_since: datetime | None = None,
) -> list[Hit]:
    """질문과 가장 가까운 기록을 돌려준다(기록마다 가장 가까운 조각 하나, per_item 을 키우면 `more` 에 조각을 더 담는다).
    family_user_ids 를 주면 그 가족 중 한 명이라도 등장한 기록만 본다(빈 목록이면 결과 없음).

    hybrid(안 주면 설정 `chat_hybrid_search`)가 켜지면 임베딩 상위 후보를 글자 TF-IDF 와 섞어 다시 정렬한다. 이때 결과 순서는
    섞은 순서이고, `Hit.score` 는 여전히 임베딩 코사인 유사도다(그래서 점수가 순서대로 내려가지 않을 수 있다).
    꺼 두면 점수 순이다. 최고 유사도만 필요한 곳(첫 호출 검색 강제)은 hybrid=False 로 부른다."""
    embedder = _embedder(db)
    mix = settings.chat_hybrid_search if hybrid is None else hybrid
    candidates = max(settings.chat_hybrid_candidates, top_k * per_item) if mix else 60
    rows = repo.search_chunks(
        db,
        group_id,
        embedder.name,
        embedder.embed_query(query),
        kind_label,
        date_from,
        date_to,
        include_sensitive,
        limit=candidates,
        family_user_ids=family_user_ids,
        created_from=created_from,
        created_to=created_to,
        created_by=created_by,
        chat_verified_since=chat_verified_since,
    )
    if mix and len(rows) > 1:
        order = hybrid_search.fuse_order(
            query, [c.text for c, _i, _s in rows], settings.chat_hybrid_text_weight
        )
        rows = [rows[i] for i in order]
    best: dict[str, Hit] = {}
    extra: dict[str, list[KnowledgeChunk]] = {}
    # 정렬 순서(섞었으면 섞은 순서)에서 기록마다 처음 나온 조각이 대표 조각이다
    for chunk, item, score in rows:
        if item.id not in best:
            best[item.id] = Hit(item=item, chunk=chunk, score=score)
        elif len(extra.setdefault(item.id, [])) < per_item - 1:
            extra[item.id].append(chunk)
    ranked = list(best.values())  # 기록은 대표 조각이 처음 나온 순서
    top = ranked if mix else sorted(ranked, key=lambda h: h.score, reverse=True)
    top = top[:top_k]
    return [replace(h, more=tuple(extra.get(h.item.id, ()))) for h in top]


IN_ITEM_CANDIDATES = 300  # 큰 문서(6만 자, 조각 100개 안팎)의 조각을 모두 후보로 본다


def search_in_item(
    db: Session,
    group_id: str,
    item_id: str,
    query: str,
    *,
    top_k: int = 5,
    include_sensitive: bool = True,
    hybrid: bool | None = None,
    chat_verified_since: datetime | None = None,
) -> list[Hit]:
    """한 기록(문서) 안에서만 질문과 가까운 조각을 찾는다. 조각마다 Hit 하나이고 쪽 순서가 아니라 순위(하이브리드면
    섞은 순서, 아니면 임베딩 점수 순) 로 top_k 개. 다른 그룹·없는 item_id·볼 수 없는 민감 기록은 빈 목록이다."""
    embedder = _embedder(db)
    mix = settings.chat_hybrid_search if hybrid is None else hybrid
    rows = repo.search_chunks(
        db,
        group_id,
        embedder.name,
        embedder.embed_query(query),
        None,
        None,
        None,
        include_sensitive,
        limit=IN_ITEM_CANDIDATES,
        item_id=item_id,
        chat_verified_since=chat_verified_since,
    )
    if mix and len(rows) > 1:
        order = hybrid_search.fuse_order(
            query, [c.text for c, _i, _s in rows], settings.chat_hybrid_text_weight
        )
        rows = [rows[i] for i in order]
    return [Hit(item=item, chunk=chunk, score=score) for chunk, item, score in rows[:top_k]]


def name_checks(db: Session, group_id: str, limit: int = 5) -> list[dict]:
    """가족 이름과 한 글자 차이인 이름이 있어 사용자 확인을 기다리는 곳(기록, 후보 가족) 목록. 오래된 것부터 limit 개.

    글자는 저장하지 않았으므로 앞뒤 글(가린 글)만 보여 준다. 같은 기록에 후보가 둘이면 각각 한 건이다."""
    names = family_names.shown_names(family_names.load_members(db, group_id))
    out: list[dict] = []
    for item in reversed(repo.items_containing(db, group_id, "[확인필요:", limit=20)):
        for uid in family_names.check_ids(item.body_md):
            out.append(
                {
                    "item_id": item.id,
                    "title": family_names.restore(item.title, names),
                    "date": item.occurred_on.isoformat() if item.occurred_on else None,
                    "candidate_id": uid,
                    "candidate": names.get(uid, family_names.NEUTRAL_NAME),
                    "context": _check_context(item.body_md, uid, names),
                }
            )
    return out[:limit]


def count_name_checks(db: Session, group_id: str) -> int:
    return sum(
        len(family_names.check_ids(i.body_md))
        for i in repo.items_containing(db, group_id, "[확인필요:", limit=50)
    )


def _check_context(body: str, user_id: str, names: dict[str, str], pad: int = 30) -> str:
    """확인할 자리 앞뒤 글. 그 자리는 '[?]', 다른 확인 자리와 가족 이름은 보이는 형태로."""
    mark = f"[확인필요:{user_id}]"
    at = body.find(mark)
    part = body[max(0, at - pad) : at + len(mark) + pad]
    part = part.replace(mark, "[?]")
    return " ".join(family_names.restore(part, names).split())


def resolve_name_check(
    db: Session, group_id: str, item_id: str, user_id: str, same_person: bool
) -> KnowledgeItem:
    """사용자의 답을 반영한다: 같은 사람이면 `[가족:<id>]`, 아니면 `[이름]` 으로 바꾸고 검색 조각을 다시 만든다.
    후보는 이 기록에 남은 확인 자리의 user_id 만 받는다(모델이 임의의 id 를 넣을 수 없다). 글은 이미 가려진 상태라 다시 가리지 않는다."""
    item = get_item(db, group_id, item_id)
    if user_id not in family_names.check_ids(item.body_md):
        raise ApiError(404, "name_check_not_found", "확인할 이름이 이 기록에 없어요")
    title = family_names.resolve_check(item.title, user_id, same_person)
    body = family_names.resolve_check(item.body_md, user_id, same_person)
    item.title, item.body_md = title, body
    item.family_user_ids = family_names.extract_ids(title, body) or None
    return repo.replace_chunks(db, item, _chunks(_embedder(db), group_id, body))


def get_item(db: Session, group_id: str, item_id: str) -> KnowledgeItem:
    item = repo.get_item(db, group_id, item_id)
    if item is None:
        raise not_found("기록")
    return item


def mark_read(db: Session, item_id: str, user_id: str) -> None:
    """상세를 연 사용자의 읽음을 남긴다(멱등)."""
    repo.mark_read(db, item_id, user_id)


def seen_ids(db: Session, user_id: str, items: list[KnowledgeItem]) -> set[str]:
    """이 사용자가 본 기록의 id: 직접 올렸거나 상세를 열어 읽음이 남은 것."""
    mine = {i.id for i in items if i.created_by == user_id}
    rest = [i.id for i in items if i.id not in mine]
    return mine | repo.seen_item_ids(db, user_id, rest)


def attach_seen(db: Session, user_id: str, items: list[KnowledgeItem]) -> list[KnowledgeItem]:
    """각 기록에 이 사용자의 읽음 여부(`seen`)를 붙여 돌려준다."""
    seen = seen_ids(db, user_id, items)
    for item in items:
        item.seen = item.id in seen
    return items


def created_bounds(
    created_from: date | None, created_to: date | None, offset_hours: int
) -> tuple[datetime | None, datetime | None]:
    """한국 시간(설정 `ai_day_utc_offset_hours`) 달력 날짜 범위(양끝 포함)를 UTC 경계(시작 이상, 끝 미만)로 바꾼다.

    시작이 끝보다 늦거나 날짜가 표현 범위를 넘으면 ValueError 를 낸다(라우터가 400 으로 바꾼다).
    """
    if created_from and created_to and created_from > created_to:
        raise ValueError("시작 날짜가 끝 날짜보다 늦을 수 없어요.")
    offset = timedelta(hours=offset_hours)
    try:
        start = (
            datetime.combine(created_from, time.min, tzinfo=UTC) - offset if created_from else None
        )
        end = (
            datetime.combine(created_to + timedelta(days=1), time.min, tzinfo=UTC) - offset
            if created_to
            else None
        )
    except OverflowError as exc:
        raise ValueError("날짜가 너무 크거나 작아요.") from exc
    return start, end


def list_items(
    db: Session,
    group_id: str,
    kind_label: str | None = None,
    limit: int = 50,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    created_by: list[str] | None = None,
) -> list[KnowledgeItem]:
    return repo.list_items(db, group_id, kind_label, limit, created_from, created_to, created_by)


def reindex(
    db: Session,
    group_id: str | None = None,
    *,
    batch_size: int | None = None,
    limit: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """다른 모델로 만든 벡터를 지금 모델로 다시 만든다. 모델을 바꾼 뒤에 부른다. 바뀐 조각 수를 돌려준다.

    `batch_size` 개씩 임베딩해 벡터와 모델 이름을 함께 쓰고 배치마다 commit 한다(None 이면 한 배치). 이미 commit 된 배치는
    중간에 실패해도 남고, 다시 부르면 남은 조각만 한다. 임베딩 중 지워진 조각은 0행 갱신으로 넘어간다. 실패한 배치는
    rollback 하고 예외를 그대로 올린다. `limit` 은 이번에 처리할 최대 조각 수, `on_progress(처리한 수, 전체 수)` 는 배치마다 부른다."""
    if batch_size is not None and batch_size < 1:
        raise ValueError("batch_size 는 1 이상이어야 해요")
    embedder = _embedder(db)
    total = repo.count_stale(db, embedder.name, group_id)
    if limit is not None:
        total = min(total, limit)
    updated = processed = last_id = 0
    while processed < total:
        size = total - processed if batch_size is None else min(batch_size, total - processed)
        batch = [
            (c.id, c.text)
            for c in repo.stale_chunks(db, embedder.name, group_id, after_id=last_id, limit=size)
        ]
        if not batch:
            break
        try:
            vectors = embedder.embed_passages([text for _, text in batch])
            for (chunk_id, _), vec in zip(batch, vectors, strict=True):
                updated += repo.update_chunk_embedding(db, chunk_id, embedder.name, vec)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        last_id = batch[-1][0]
        processed += len(batch)
        if on_progress:
            on_progress(processed, total)
    return updated
