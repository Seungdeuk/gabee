"""추억 후보 발견(PR5): 한 가족의 사진 중 **분석 자격이 있는 사진만** 골라 `grouping.group_photos` 로 묶는다. 결과는 저장하지도 공개하지도 않는다(요청할 때마다 새로 계산하므로
동의 철회·삭제·제외·가족 끄기가 바로 반영된다). 자동 등록·게시 경로는 없다.

자격은 PR1 `service.check_photo` 하나를 그대로 쓴다(서버 스위치·가족 활성화·업로더 동의·사진별 제외·가족 전체방·확인된 일반 사진). 자격이 없는 사진은 이유 코드별 개수만 세고 그룹화에
넘기지 않는다. 임베딩·화질 값은 주입한 함수로 받는다(PR6 이 `photo_embeddings`·저장된 사진 파일에서 읽는 함수를 연결한다). 값이 없으면 그 근거 없이 그룹화한다.
다른 가족의 사진은 조회 자체에 포함되지 않는다(`group_id` 로만 읽는다)."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import repository as repo
from . import service
from .grouping import GroupingConfig, MemoryCandidate, PhotoFeatures, group_photos
from .quality import ImageStats

EmbeddingLookup = Callable[[str], tuple[float, ...] | list[float] | None]  # attachment_id → 임베딩
StatsLookup = Callable[[str], ImageStats | None]  # attachment_id → 화질·해시 값


@dataclass(frozen=True)
class DiscoveryResult:
    group_id: str
    candidates: list[MemoryCandidate] = field(default_factory=list)
    considered: int = 0  # 가족 전체방 사진 수
    eligible: int = 0  # 자격이 있어 그룹화에 넘긴 사진 수
    skipped: dict[str, int] = field(default_factory=dict)  # 자격 없는 사유 코드별 개수


def discover(
    db: Session,
    group_id: str,
    embeddings: EmbeddingLookup | None = None,
    stats: StatsLookup | None = None,
    config: GroupingConfig | None = None,
) -> DiscoveryResult:
    """가족 하나의 추억 후보를 계산한다. 서버 스위치가 꺼져 있거나 자격 있는 사진이 없으면 후보는 빈 목록이다."""
    rows = repo.group_photo_rows(db, group_id)
    features: list[PhotoFeatures] = []
    skipped: Counter[str] = Counter()
    for row in rows:
        eligibility = service.check_photo(db, row.attachment_id)
        if not eligibility.eligible:
            skipped[eligibility.reason] += 1
            continue
        embedding = embeddings(row.attachment_id) if embeddings is not None else None
        st = stats(row.attachment_id) if stats is not None else None
        features.append(
            PhotoFeatures(
                attachment_id=row.attachment_id,
                group_id=row.group_id,
                uploader_id=row.uploader_id,
                uploaded_at=row.uploaded_at,
                taken_at=row.taken_at,
                batch_id=row.batch_id,
                embedding=tuple(embedding) if embedding is not None else None,
                content_hash=st.content_hash if st else None,
                dhash=st.dhash if st else None,
                sharpness=st.sharpness if st else None,
                exposure=st.exposure if st else None,
            )
        )
    return DiscoveryResult(
        group_id=group_id,
        candidates=group_photos(features, config),
        considered=len(rows),
        eligible=len(features),
        skipped=dict(skipped),
    )
