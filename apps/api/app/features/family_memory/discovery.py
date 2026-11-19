"""추억 후보 발견: 한 가족의 사진 중 **분석 자격이 있는 사진만** 골라 `grouping.group_photos` 로 묶는다. 읽기 전용이며 자동 등록·게시 경로는 없다.

자격은 PR1 판정 규칙(`service.evaluate`)을 가족 단위로 **일괄** 적용한다(`service.check_group_photos`: 사진 수와 무관하게 조회 4번). 자격이 없는 사진은 이유 코드별 개수만 세고
그룹화에 넘기지 않는다. 임베딩·화질 값은 두 가지 방법으로 받는다: `discover(embeddings=…, stats=…)` 는 주입한 함수(시험·실험용), `discover_group` 은 실제 데이터 —
PR4 `photo_embeddings`(한 번의 일괄 조회)와 저장된 사진 파일(EXIF 없는 JPEG)에서 계산한 `ImageStats`. 값이 없으면 그 근거 없이 그룹화하고, 촬영 시각이 없으면 업로드 시각으로
대체하지 않는다. 사진 내용·경로·EXIF 는 로그에 남기지 않는다. 다른 가족의 사진은 조회에 포함되지 않는다(`group_id` 로만 읽는다)."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from . import embedding_repository as embeddings_repo
from . import service
from .encoder import EncoderError, unpack
from .grouping import GroupingConfig, MemoryCandidate, PhotoFeatures, group_photos
from .quality import ImageStats, image_stats

EmbeddingLookup = Callable[[str], tuple[float, ...] | list[float] | None]  # attachment_id → 임베딩
StatsLookup = Callable[[str], ImageStats | None]  # attachment_id → 화질·해시 값


@dataclass(frozen=True)
class DiscoveryResult:
    group_id: str
    candidates: list[MemoryCandidate] = field(default_factory=list)
    considered: int = 0  # 가족 전체방 사진 수
    eligible: int = 0  # 자격이 있어 그룹화에 넘긴 사진 수
    skipped: dict[str, int] = field(default_factory=dict)  # 자격 없는 사유 코드별 개수
    uploaders: dict[str, str] = field(
        default_factory=dict
    )  # 자격 있는 사진의 attachment_id → 올린 사람(후보 저장·정리용)


def _select(db: Session, group_id: str):
    photos, eligibility = service.check_group_photos(db, group_id)
    skipped: Counter[str] = Counter()
    eligible = []
    for p in photos:
        verdict = eligibility[p.attachment_id]
        if verdict.eligible:
            eligible.append(p)
        else:
            skipped[verdict.reason] += 1
    return photos, eligible, dict(skipped)


def _features(eligible, embeddings: EmbeddingLookup | None, stats: StatsLookup | None):
    out: list[PhotoFeatures] = []
    for p in eligible:
        embedding = embeddings(p.attachment_id) if embeddings is not None else None
        st = stats(p.attachment_id) if stats is not None else None
        out.append(
            PhotoFeatures(
                attachment_id=p.attachment_id,
                group_id=p.group_id,
                uploader_id=p.uploader_id,
                uploaded_at=p.uploaded_at,
                taken_at=p.taken_at,  # 없으면 None 그대로(업로드 시각으로 대체하지 않는다)
                batch_id=p.batch_id,
                embedding=tuple(embedding) if embedding is not None else None,
                content_hash=st.content_hash if st else None,
                dhash=st.dhash if st else None,
                sharpness=st.sharpness if st else None,
                exposure=st.exposure if st else None,
            )
        )
    return out


def discover(
    db: Session,
    group_id: str,
    embeddings: EmbeddingLookup | None = None,
    stats: StatsLookup | None = None,
    config: GroupingConfig | None = None,
) -> DiscoveryResult:
    """주입한 임베딩·화질 함수로 가족 하나의 추억 후보를 계산한다. 자격 있는 사진이 없으면 후보는 빈 목록이다."""
    photos, eligible, skipped = _select(db, group_id)
    return DiscoveryResult(
        group_id=group_id,
        candidates=group_photos(_features(eligible, embeddings, stats), config),
        considered=len(photos),
        eligible=len(eligible),
        skipped=skipped,
        uploaders={p.attachment_id: p.uploader_id for p in eligible},
    )


def photo_stats(attachment_id: str) -> ImageStats | None:
    """저장된 사진 파일(채팅이 만든 EXIF 없는 JPEG)에서 화질·해시를 계산한다. 파일이 없거나 열 수 없으면 None. 내용·경로는 로그에 남기지 않는다."""
    from .analysis import photo_file

    path = photo_file(attachment_id)
    if path is None:
        return None
    try:
        return image_stats(path.read_bytes())
    except OSError:
        return None


def discover_group(
    db: Session, group_id: str, config: GroupingConfig | None = None
) -> DiscoveryResult:
    """실제 데이터로 가족 하나의 추억 후보를 계산한다: 자격(일괄) → 임베딩(일괄 한 번) → 사진 파일의 ImageStats → 그룹화. 읽기 전용."""
    photos, eligible, skipped = _select(db, group_id)
    rows = embeddings_repo.get_many(db, [p.attachment_id for p in eligible])
    vectors: dict[str, tuple[float, ...]] = {}
    for att, row in rows.items():
        try:
            vectors[att] = tuple(unpack(row.vector, row.dim))
        except EncoderError:
            continue  # 깨진 줄은 이미지 근거 없이 처리한다
    return DiscoveryResult(
        group_id=group_id,
        candidates=group_photos(_features(eligible, vectors.get, photo_stats), config),
        considered=len(photos),
        eligible=len(eligible),
        skipped=skipped,
        uploaders={p.attachment_id: p.uploader_id for p in eligible},
    )
