"""추억 후보(`memory_candidates`·`memory_candidate_photos`) DB 접근(PR6). 커밋은 부르는 쪽이 한다. 사진 자체는 저장하지 않고 첨부 id 와 순서뿐이다."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import MemoryCandidate, MemoryCandidatePhoto

CHUNK = 500


def list_for_group(db: Session, group_id: str) -> list[MemoryCandidate]:
    return list(
        db.scalars(
            select(MemoryCandidate)
            .where(MemoryCandidate.group_id == group_id)
            .order_by(MemoryCandidate.score.desc(), MemoryCandidate.id)
        )
    )


def photos_for(db: Session, candidate_ids: list[str]) -> dict[str, list[MemoryCandidatePhoto]]:
    """후보별 포함 사진(순서대로). 한 번(또는 큰 목록이면 몇 번)의 조회."""
    out: dict[str, list[MemoryCandidatePhoto]] = {cid: [] for cid in candidate_ids}
    for i in range(0, len(candidate_ids), CHUNK):
        part = candidate_ids[i : i + CHUNK]
        rows = db.scalars(
            select(MemoryCandidatePhoto)
            .where(MemoryCandidatePhoto.candidate_id.in_(part))
            .order_by(MemoryCandidatePhoto.candidate_id, MemoryCandidatePhoto.position)
        )
        for row in rows:
            out[row.candidate_id].append(row)
    return out


def delete_candidates(db: Session, candidate_ids: list[str]) -> int:
    """후보와 그 사진 줄을 지운다(SQLite 는 연쇄 삭제가 없어 사진 줄을 먼저 지운다)."""
    total = 0
    for i in range(0, len(candidate_ids), CHUNK):
        part = candidate_ids[i : i + CHUNK]
        db.execute(delete(MemoryCandidatePhoto).where(MemoryCandidatePhoto.candidate_id.in_(part)))
        total += (
            db.execute(delete(MemoryCandidate).where(MemoryCandidate.id.in_(part))).rowcount or 0
        )
    return total


def candidate_ids_with_photos(db: Session, *conditions) -> list[str]:
    """조건에 맞는 사진 줄이 하나라도 있는 후보의 id."""
    return sorted(set(db.scalars(select(MemoryCandidatePhoto.candidate_id).where(*conditions))))


def candidate_ids_of_group(db: Session, group_id: str) -> list[str]:
    return list(db.scalars(select(MemoryCandidate.id).where(MemoryCandidate.group_id == group_id)))
