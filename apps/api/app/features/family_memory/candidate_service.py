"""추억 후보 저장·조회(PR6). 후보는 **비공개**(`private`)로만 저장하고 자동으로 게시하지 않는다. 후보를 만드는 자동 경로(자동 등록)는 없다 — `refresh` 는 부르는 쪽(운영 도구·이후 승인된 진입점)이
명시적으로 호출해야 하고, 조회 API 는 읽기 전용이다.

- `refresh(db, group_id)`: `discovery.discover_group`(자격 일괄 조회 → 임베딩 일괄 조회 → ImageStats → PR5 그룹화)의 결과를 저장한다. 후보 식별자가 가족+포함 사진으로 정해지는 결정적 값이라
  **같은 입력으로 다시 해도 한 줄**이고(내용이 같으면 `updated_at` 도 그대로), 더는 발견되지 않는 이전 후보는 지운다(사진이 바뀌면 식별자도 바뀐다).
- `list_for_family(db, group_id)`: 저장본을 **읽을 때마다 자격을 다시 확인**한다(일괄 4번 조회). 지운·철회·제외·자격 잃은 사진은 응답에서 빠지고, 그 사진의 촬영 시각 같은 메타데이터도
  남지 않게 시각 범위는 남은 사진으로 다시 계산한다. 대표 사진이 무효가 되면 남은 대표 후보 → 남은 첫 장면 순으로 다시 고르고, 중복을 뺀 장면이 `min_unique_photos`(3) 미만이면 후보를 숨긴다.
- 정리: 동의 철회·가족 나가기·가족 끄기·사진별 제외·사진 삭제 때 그 사진이 든 후보를 통째로 지운다(`memory_hooks`, 같은 트랜잭션의 최선 노력). 못 지워도 조회 때 재검증으로 안 보이고 `reconcile` 이 뒤늦게 지운다."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import memory_hooks

from . import candidate_repository as repo
from . import discovery, reconcile, service
from . import job_service as js
from .grouping import ALGORITHM_VERSION, GroupingConfig, MemoryCandidate
from .models import MemoryCandidate as CandidateRow
from .models import MemoryCandidatePhoto

logger = logging.getLogger(__name__)

STATUS_PRIVATE = "private"
MIN_UNIQUE = GroupingConfig().min_unique_photos


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RefreshResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    considered: int = 0
    eligible: int = 0


@dataclass(frozen=True)
class ViewPhoto:
    attachment_id: str
    taken_at: datetime | None
    is_representative: bool


@dataclass(frozen=True)
class CandidateView:
    id: str
    representative_id: str
    photos: list[ViewPhoto]
    dated_count: int
    undated_count: int
    starts_at: datetime | None
    ends_at: datetime | None
    bridged: bool
    score: float
    algorithm_version: str
    status: str
    updated_at: datetime


# ---------- 저장 ----------
def _evidence(c: MemoryCandidate) -> dict:
    te = c.time_evidence
    return {
        "basis": te.basis,
        "start": te.start.isoformat(),
        "end": te.end.isoformat(),
        "dated_count": te.dated_count,
        "batch_attached_count": te.batch_attached_count,
        "bridged": te.bridged,
    }


def _photo_rows(c: MemoryCandidate, uploaders: dict[str, str]) -> list[dict]:
    dup = dict(c.duplicates)
    ranks = {a: i for i, a in enumerate(c.representative_ids)}
    return [
        {
            "attachment_id": a,
            "user_id": uploaders[a],
            "position": i,
            "rank": ranks.get(a),
            "duplicate_of": dup.get(a),
        }
        for i, a in enumerate(c.attachment_ids)
    ]


def _signature(score: float, evidence: dict, rep: str | None, version: str, photos: list[dict]):
    return (
        round(score, 4),
        sorted(evidence.items()),
        rep,
        version,
        [(p["attachment_id"], p["position"], p["rank"], p["duplicate_of"]) for p in photos],
    )


def refresh(
    db: Session,
    group_id: str,
    config: GroupingConfig | None = None,
    enforce_retro: bool = False,
) -> RefreshResult:
    """가족 하나의 추억 후보를 새로 계산해 저장한다(멱등). 먼저 파생 데이터 대조 정리를 한 번 한다. 서버 스위치·가족 설정이 꺼져 있으면 후보는 없고 저장본도 지워진다."""
    reconcile.reconcile(db)
    result = discovery.discover_group(db, group_id, config, enforce_retro)
    now = _now()
    existing = {row.id: row for row in repo.list_for_group(db, group_id)}
    stored_photos = repo.photos_for(db, list(existing))
    created = updated = unchanged = 0
    keep: set[str] = set()
    try:
        for cand in result.candidates:
            keep.add(cand.candidate_id)
            evidence = _evidence(cand)
            photos = _photo_rows(cand, result.uploaders)
            row = existing.get(cand.candidate_id)
            if row is not None:
                old = [
                    {
                        "attachment_id": p.attachment_id,
                        "position": p.position,
                        "rank": p.rank,
                        "duplicate_of": p.duplicate_of,
                    }
                    for p in stored_photos.get(row.id, [])
                ]
                same = _signature(
                    row.score, row.evidence, row.representative_id, row.algorithm_version, old
                ) == _signature(
                    cand.score, evidence, cand.representative_id, cand.algorithm_version, photos
                )
                if same:
                    unchanged += 1
                    continue
                row.score, row.evidence = cand.score, evidence
                row.representative_id, row.algorithm_version = (
                    cand.representative_id,
                    cand.algorithm_version,
                )
                row.updated_at = now
                for p in stored_photos.get(row.id, []):
                    db.delete(p)
                db.flush()
                updated += 1
            else:
                row = CandidateRow(
                    id=cand.candidate_id,
                    group_id=group_id,
                    representative_id=cand.representative_id,
                    status=STATUS_PRIVATE,
                    score=cand.score,
                    evidence=evidence,
                    algorithm_version=cand.algorithm_version,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
                created += 1
            for p in photos:
                db.add(MemoryCandidatePhoto(candidate_id=cand.candidate_id, group_id=group_id, **p))
        stale = [cid for cid in existing if cid not in keep]
        removed = repo.delete_candidates(db, stale) if stale else 0
        # 계산하는 사이에 철회·가족 끄기가 커밋됐을 수 있다: 저장 직전에 한 번 더 대조해, 막 철회한 사람의 사진이 든 후보가 저장된 채 남지 않게 한다
        db.flush()  # 방금 추가한 후보·사진 줄이 대조 조회에 보이도록(자동 flush 가 꺼져 있다)
        reconcile.reconcile(db)
        db.commit()
    except IntegrityError:
        db.rollback()  # 같은 가족을 동시에 새로 고쳤다: 먼저 끝난 쪽의 결과가 맞다
        raise
    except Exception:
        db.rollback()
        raise
    return RefreshResult(created, updated, unchanged, removed, result.considered, result.eligible)


# ---------- 조회(자격 재검증) ----------
def list_for_family(db: Session, group_id: str) -> list[CandidateView]:
    """현재 가족의 저장된 후보를 읽되, 조회할 때마다 자격을 다시 확인한다. 서버 스위치·가족 설정이 꺼져 있으면 빈 목록."""
    if not service.server_enabled() or not service.repo.family_enabled(db, group_id):
        return []
    rows = repo.list_for_group(db, group_id)
    if not rows:
        return []
    stored = repo.photos_for(db, [r.id for r in rows])
    photos, eligibility = service.check_group_photos(db, group_id)
    alive = {p.attachment_id: p for p in photos if eligibility[p.attachment_id].eligible}
    views: list[CandidateView] = []
    for row in rows:
        members = [p for p in stored.get(row.id, []) if p.attachment_id in alive]
        scenes = {p.duplicate_of or p.attachment_id for p in members}
        if len(scenes) < MIN_UNIQUE:
            continue  # 남은 사진이 후보로 보기엔 모자라다(PR5 최소 크기 정책)
        rep = _choose_representative(row.representative_id, members)
        if rep is None:
            continue
        taken = [alive[p.attachment_id].taken_at for p in members]
        dated = [t for t in taken if t is not None]
        views.append(
            CandidateView(
                id=row.id,
                representative_id=rep,
                photos=[
                    ViewPhoto(
                        p.attachment_id, alive[p.attachment_id].taken_at, p.attachment_id == rep
                    )
                    for p in members
                ],
                dated_count=len(dated),
                undated_count=len(taken) - len(dated),
                starts_at=min(dated)
                if dated
                else None,  # 남은 사진으로 다시 계산: 빠진 사진의 시각이 남지 않는다
                ends_at=max(dated) if dated else None,
                bridged=bool(row.evidence.get("bridged", False)),
                score=row.score,
                algorithm_version=row.algorithm_version,
                status=row.status,
                updated_at=row.updated_at,
            )
        )
    return views


def _choose_representative(
    stored_rep: str | None, members: list[MemoryCandidatePhoto]
) -> str | None:
    """저장된 대표가 아직 유효하면 그대로, 아니면 남은 대표 후보 순위 → 남은 중복 아닌 첫 사진 → 남은 첫 사진 순으로 다시 고른다. 사진이 없으면 None."""
    by_id = {p.attachment_id: p for p in members}
    if stored_rep in by_id:
        return stored_rep
    ranked = sorted((p for p in members if p.rank is not None), key=lambda p: p.rank)
    if ranked:
        return ranked[0].attachment_id
    primaries = [p for p in members if p.duplicate_of is None]
    pick = primaries or members
    return pick[0].attachment_id if pick else None


# ---------- 정리 훅: 그 사진이 든 후보를 통째로 지운다 ----------
def _feature_ready() -> bool:
    return js._feature_ready()


def _delete_with(db: Session, *conditions) -> None:
    ids = repo.candidate_ids_with_photos(db, *conditions)
    if ids:
        repo.delete_candidates(db, ids)


def _on_member_withdrawn(db: Session, group_id: str, user_id: str) -> None:
    if _feature_ready():
        _delete_with(
            db, MemoryCandidatePhoto.group_id == group_id, MemoryCandidatePhoto.user_id == user_id
        )


def _on_family_disabled(db: Session, group_id: str) -> None:
    if _feature_ready():
        ids = repo.candidate_ids_of_group(db, group_id)
        if ids:
            repo.delete_candidates(db, ids)


def _on_photo_excluded(db: Session, group_id: str, attachment_id: str) -> None:
    if _feature_ready():
        _delete_with(db, MemoryCandidatePhoto.attachment_id == attachment_id)


def _on_attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    if not _feature_ready():
        return
    try:
        _delete_with(db, MemoryCandidatePhoto.attachment_id == attachment_id)
        db.commit()
    except Exception:
        db.rollback()
        raise


memory_hooks.register_member_withdrawn(_on_member_withdrawn)
memory_hooks.register_family_disabled(_on_family_disabled)
memory_hooks.register_photo_excluded(_on_photo_excluded)
memory_hooks.register_attachment_removed(_on_attachment_removed)

__all__ = ["ALGORITHM_VERSION", "refresh", "list_for_family"]
