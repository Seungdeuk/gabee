"""추억 후보 그룹화(PR5): 가족 사진을 **촬영 시각·같이 올린 묶음(batch_id)·이미지 임베딩 유사도·중복 여부**로 묶고 대표 사진을 고른다. 순수 함수 모듈이다 —
DB·파일·모델·네트워크를 쓰지 않고, 입력 순서가 바뀌어도 결과가 같다(모든 정렬·동점 처리가 결정적). 자격(동의·확인된 사진·1:1 제외 등)은 이 모듈의 일이 아니라
`discovery.py` 가 PR1 `check_photo` 로 걸러서 넘긴다.

원칙(요구사항): 같은 가족의 사진만 함께 처리한다. **업로드 시각을 촬영 시각으로 단정하지 않는다**: 시간 근거는 `taken_at` 뿐이고, `taken_at` 이 없는 사진은 시간만으로
그룹을 만들거나 합류하지 않는다. `batch_id` 는 "함께 전송했다"는 근거일 뿐 같은 사건의 확증이 아니다: 날짜 있는 사진을 서로 묶지 않고, 날짜 없는 사진을 **같은 묶음의 날짜 있는
사진이 모두 한 그룹에 있고 이미지도 그 그룹과 비슷할 때만** 그 그룹에 붙인다. 서로 다른 연도(긴 시간 간격)의 비슷한 장면은 시간 간격 때문에 합쳐지지 않는다. 정보가 부족하면 그룹을 만들지 않는다.
장소·인물·관계·감정은 추론하지 않는다(출력에도 없다).

알고리즘 `memgrp-1`: ① 가족별로 나눈다 ② 날짜 있는 사진을 촬영 시각순으로 훑으며 시간 간격이 `gap_hours` 를 넘거나(또는 `soft_gap_minutes` 를 넘고 그룹 중심과의 코사인 유사도가
`split_cos` 아래) 이면 새 그룹 ③ 인접 그룹이 `bridge_hours` 안이고 중심 유사도가 `bridge_cos` 이상이면 다일 이벤트로 이음 ④ 날짜 없는 사진은 batch_id 규칙으로만 붙임
⑤ 중복(같은 내용 해시 / dHash 해밍 거리 / 임베딩 코사인)을 한 덩어리로 묶고 가장 좋은 한 장만 "대표 후보"로 둠(원본은 지우지 않는다) ⑥ 중복을 뺀 사진이 `min_unique_photos` 미만이면
그룹을 내지 않음 ⑦ 대표 사진은 화질·노출·그룹 중심 대표성으로 점수를 매기고 MMR 로 다양하게 고른다. 가중치는 정답이 아니라 초기값이며 합성 라벨 데이터로 점검한다(`scripts/grouping_synthetic_eval.py`)."""

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

ALGORITHM_VERSION = "memgrp-1"


@dataclass(frozen=True)
class PhotoFeatures:
    """사진 한 장의 그룹화 입력(사진 내용은 없다). `embedding` 은 정규화되지 않아도 된다(없거나 잘못된 값이면 이미지 근거 없음). 화질 값은 0~1."""

    attachment_id: str
    group_id: str  # 가족 그룹 ID
    uploader_id: str
    uploaded_at: datetime  # 근거로만 기록한다. 촬영 시각으로 쓰지 않는다
    taken_at: datetime | None = None
    batch_id: str | None = None
    embedding: tuple[float, ...] | None = None
    content_hash: str | None = None  # 같은 바이트면 같은 값(sha256 등)
    dhash: int | None = None  # 64비트 지각 해시
    sharpness: float | None = None
    exposure: float | None = None


@dataclass(frozen=True)
class GroupingConfig:
    gap_hours: float = 8.0
    soft_gap_minutes: float = 30.0  # 이 안(연사·한 장면)이면 이미지가 달라도 같은 그룹으로 본다
    split_cos: float = 0.70
    bridge_hours: float = 36.0
    bridge_cos: float = 0.85
    batch_attach_cos: float = 0.80
    dup_cos: float = 0.985
    dup_hamming: int = 4
    min_unique_photos: int = 3
    w_quality: float = 0.5
    w_central: float = 0.5
    mmr_lambda: float = 0.7
    dup_penalty: float = 0.15
    max_representatives: int = 3


@dataclass(frozen=True)
class TimeEvidence:
    """그룹화에 쓴 시각 근거. 기준은 항상 촬영 시각(`taken_at`)이다."""

    basis: str  # "taken_at"
    start: datetime
    end: datetime
    dated_count: int  # 촬영 시각이 있는 사진 수
    batch_attached_count: int  # 촬영 시각이 없어 같은 묶음(batch_id)+이미지 유사도로만 붙은 사진 수
    bridged: bool  # 시간 간격이 길지만 이미지가 비슷해 이은 그룹인가(다일 이벤트 후보)


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str  # 가족 + 포함 사진으로 정해지는 결정적 식별자(입력 순서와 무관)
    group_id: str
    attachment_ids: tuple[str, ...]  # 중복 포함 모든 사진(촬영 시각순, 날짜 없는 것은 뒤)
    representative_id: str
    representative_ids: tuple[str, ...]  # 다양성을 고려한 대표 후보(첫 번째가 representative_id)
    duplicates: tuple[tuple[str, str], ...]  # (중복 사진, 남긴 사진). 원본은 지우지 않는다
    time_evidence: TimeEvidence
    score: float  # 0~1, 후보 우선순위용(정답 확률이 아니다)
    algorithm_version: str = ALGORITHM_VERSION


# ---------- 작은 도구 ----------
def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _unit(vector: tuple[float, ...] | None) -> tuple[float, ...] | None:
    """정규화한 벡터. 비었거나 유한하지 않거나 크기가 0 이면 None(이미지 근거 없음)."""
    if not vector:
        return None
    if any(not math.isfinite(v) for v in vector):
        return None
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0 or not math.isfinite(norm):
        return None
    return tuple(v / norm for v in vector)


def _cos(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b):
        return -1.0  # 차원이 다르면(모델이 다름) 비슷하다고 보지 않는다
    return sum(x * y for x, y in zip(a, b, strict=True))


def _centroid(vectors: list[tuple[float, ...]]) -> tuple[float, ...] | None:
    vectors = [v for v in vectors if v]
    if not vectors:
        return None
    dim = len(vectors[0])
    vectors = [v for v in vectors if len(v) == dim]
    return _unit(tuple(sum(v[i] for v in vectors) / len(vectors) for i in range(dim)))


def _hamming(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def _quality(p: PhotoFeatures) -> float:
    sharp = 0.5 if p.sharpness is None else min(max(p.sharpness, 0.0), 1.0)
    expo = 0.5 if p.exposure is None else min(max(p.exposure, 0.0), 1.0)
    return 0.6 * sharp + 0.4 * expo


@dataclass
class _Work:
    photo: PhotoFeatures
    unit: tuple[float, ...] | None = None
    taken: datetime | None = None
    attached: bool = False  # 촬영 시각 없이 batch_id 규칙으로 붙은 사진
    extra: dict = field(default_factory=dict)


def _work(p: PhotoFeatures) -> _Work:
    return _Work(p, _unit(p.embedding), _utc(p.taken_at) if p.taken_at is not None else None)


# ---------- 공개 함수 ----------
def group_photos(
    photos: list[PhotoFeatures], config: GroupingConfig | None = None
) -> list[MemoryCandidate]:
    """사진들을 추억 후보 그룹으로 묶는다. 가족(`group_id`)마다 따로 처리하고 서로 섞지 않는다. 같은 `attachment_id` 가 여럿이면 첫 번째만 쓴다.
    입력 순서와 무관하게 같은 결과를 낸다. 그룹을 만들 근거가 부족하면 빈 목록."""
    cfg = config or GroupingConfig()
    seen: set[str] = set()
    by_family: dict[str, list[PhotoFeatures]] = defaultdict(list)
    for p in sorted(photos, key=lambda p: p.attachment_id):
        if p.attachment_id in seen:
            continue
        seen.add(p.attachment_id)
        by_family[p.group_id].append(p)
    out: list[MemoryCandidate] = []
    for group_id in sorted(by_family):
        out.extend(_group_family(group_id, by_family[group_id], cfg))
    return sorted(out, key=lambda c: (c.group_id, c.time_evidence.start, c.candidate_id))


def _split_by_time(dated: list[_Work], cfg: GroupingConfig) -> list[list[_Work]]:
    gap = timedelta(hours=cfg.gap_hours)
    soft = timedelta(minutes=cfg.soft_gap_minutes)
    segments: list[list[_Work]] = []
    current: list[_Work] = []
    for w in dated:
        if not current:
            current = [w]
            continue
        delta = w.taken - current[-1].taken
        split = delta > gap
        if not split and delta > soft and w.unit is not None:
            centroid = _centroid([m.unit for m in current if m.unit is not None])
            if centroid is not None and _cos(centroid, w.unit) < cfg.split_cos:
                split = True
        if split:
            segments.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        segments.append(current)
    return segments


def _bridge(segments: list[list[_Work]], cfg: GroupingConfig) -> list[tuple[list[_Work], bool]]:
    """인접 그룹이 `bridge_hours` 안이고 이미지 중심이 충분히 비슷하면 하나로 잇는다(다일 이벤트). 다른 연도처럼 간격이 크면 절대 잇지 않는다."""
    merged: list[tuple[list[_Work], bool]] = []
    bridge = timedelta(hours=cfg.bridge_hours)
    for seg in segments:
        if merged:
            prev, was_bridged = merged[-1]
            gap = seg[0].taken - prev[-1].taken
            a = _centroid([m.unit for m in prev if m.unit is not None])
            b = _centroid([m.unit for m in seg if m.unit is not None])
            if gap <= bridge and a is not None and b is not None and _cos(a, b) >= cfg.bridge_cos:
                merged[-1] = (prev + seg, True)
                continue
        merged.append((seg, False))
    return merged


def _group_family(
    group_id: str, photos: list[PhotoFeatures], cfg: GroupingConfig
) -> list[MemoryCandidate]:
    works = [_work(p) for p in photos]
    dated = sorted(
        (w for w in works if w.taken is not None), key=lambda w: (w.taken, w.photo.attachment_id)
    )
    undated = [w for w in works if w.taken is None]
    segments = _bridge(_split_by_time(dated, cfg), cfg)

    # 날짜 없는 사진: 같은 batch_id 의 날짜 있는 사진이 모두 한 그룹에 있고 그 그룹과 이미지가 비슷할 때만 붙인다
    batch_to_groups: dict[str, set[int]] = defaultdict(set)
    for idx, (seg, _) in enumerate(segments):
        for w in seg:
            if w.photo.batch_id:
                batch_to_groups[w.photo.batch_id].add(idx)
    attached: dict[int, list[_Work]] = defaultdict(list)
    for w in undated:
        batch = w.photo.batch_id
        if not batch or w.unit is None:
            continue
        targets = batch_to_groups.get(batch, set())
        if len(targets) != 1:
            continue  # 날짜 있는 같은 묶음 사진이 없거나 여러 그룹에 흩어져 있다: 근거 부족
        idx = next(iter(targets))
        centroid = _centroid([m.unit for m in segments[idx][0] if m.unit is not None])
        if centroid is not None and _cos(centroid, w.unit) >= cfg.batch_attach_cos:
            w.attached = True
            attached[idx].append(w)

    out = []
    for idx, (seg, bridged) in enumerate(segments):
        candidate = _make_candidate(group_id, seg, attached.get(idx, []), bridged, cfg)
        if candidate is not None:
            out.append(candidate)
    return out


def _duplicate_components(members: list[_Work], cfg: GroupingConfig) -> list[list[_Work]]:
    """같은 내용 해시이거나 dHash 가 거의 같거나 임베딩이 거의 같은 사진을 한 덩어리로 묶는다(union-find)."""
    parent = list(range(len(members)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a, b = members[i], members[j]
            same = a.photo.content_hash is not None and a.photo.content_hash == b.photo.content_hash
            near_hash = (
                a.photo.dhash is not None
                and b.photo.dhash is not None
                and _hamming(a.photo.dhash, b.photo.dhash) <= cfg.dup_hamming
            )
            near_emb = (
                a.unit is not None and b.unit is not None and _cos(a.unit, b.unit) >= cfg.dup_cos
            )
            if same or near_hash or near_emb:
                parent[find(i)] = find(j)
    comps: dict[int, list[_Work]] = defaultdict(list)
    for i, w in enumerate(members):
        comps[find(i)].append(w)
    return list(comps.values())


def _order_key(w: _Work) -> tuple:
    return (w.taken is None, w.taken or datetime.max.replace(tzinfo=UTC), w.photo.attachment_id)


def _make_candidate(
    group_id: str,
    seg: list[_Work],
    attached: list[_Work],
    bridged: bool,
    cfg: GroupingConfig,
) -> MemoryCandidate | None:
    members = sorted(seg + attached, key=_order_key)
    components = _duplicate_components(members, cfg)
    primaries: list[tuple[_Work, int]] = []  # (남긴 사진, 덩어리 크기)
    duplicates: list[tuple[str, str]] = []
    for comp in components:
        best = min(  # 화질이 가장 좋은 한 장, 동점이면 촬영 시각이 이른 것, 그다음 id 사전순
            comp,
            key=lambda w: (
                -_quality(w.photo),
                w.taken is None,
                w.taken or datetime.max.replace(tzinfo=UTC),
                w.photo.attachment_id,
            ),
        )
        primaries.append((best, len(comp)))
        duplicates.extend(
            (w.photo.attachment_id, best.photo.attachment_id) for w in comp if w is not best
        )
    if len(primaries) < cfg.min_unique_photos:
        return None  # 중복을 빼면 추억으로 보기에 사진이 모자란다

    primaries.sort(key=lambda pc: _order_key(pc[0]))
    centroid = _centroid([w.unit for w, _ in primaries if w.unit is not None])

    def base(item: tuple[_Work, int]) -> float:
        w, size = item
        central = 0.5 if (centroid is None or w.unit is None) else max(_cos(centroid, w.unit), 0.0)
        raw = cfg.w_quality * _quality(w.photo) + cfg.w_central * central
        return raw / (1.0 + cfg.dup_penalty * (size - 1))  # 중복이 많은 장면의 비중을 줄인다

    reps = _select_representatives(primaries, base, cfg)

    dated_unique = [w for w, _ in primaries if w.taken is not None]
    taken_times = sorted(w.taken for w in members if w.taken is not None)
    start, end = taken_times[0], taken_times[-1]
    span_hours = (end - start).total_seconds() / 3600
    cohesion = (
        sum(max(_cos(centroid, w.unit), 0.0) for w, _ in primaries if w.unit is not None)
        / max(sum(1 for w, _ in primaries if w.unit is not None), 1)
        if centroid is not None
        else 0.5
    )
    size_score = min(1.0, math.log(1 + len(primaries)) / math.log(13))
    compact = 1.0 if span_hours <= 24 else 1.0 / (1.0 + (span_hours - 24) / 48)
    score = round(
        0.35 * size_score
        + 0.35 * cohesion
        + 0.15 * compact
        + 0.15 * (len(dated_unique) / len(primaries)),
        4,
    )
    ids = tuple(w.photo.attachment_id for w in members)
    digest = hashlib.sha1(
        f"{group_id}|{','.join(sorted(ids))}".encode(), usedforsecurity=False
    ).hexdigest()[:16]
    return MemoryCandidate(
        candidate_id=digest,
        group_id=group_id,
        attachment_ids=ids,
        representative_id=reps[0],
        representative_ids=tuple(reps),
        duplicates=tuple(sorted(duplicates)),
        time_evidence=TimeEvidence(
            basis="taken_at",
            start=start,
            end=end,
            dated_count=sum(1 for w in members if w.taken is not None),
            batch_attached_count=len(attached),
            bridged=bridged,
        ),
        score=score,
    )


def _select_representatives(primaries, base, cfg: GroupingConfig) -> list[str]:
    """MMR: 첫 장은 기본 점수가 가장 높은 사진, 그다음은 (기본 점수 − 이미 고른 사진과의 유사도)가 높은 사진. 동점은 id 사전순."""
    remaining = sorted(primaries, key=lambda pc: pc[0].photo.attachment_id)
    chosen: list[_Work] = []
    ids: list[str] = []
    while remaining and len(ids) < cfg.max_representatives:
        best_item, best_value = None, -math.inf
        for item in remaining:
            w = item[0]
            if chosen:
                sim = max(
                    (
                        _cos(w.unit, c.unit)
                        for c in chosen
                        if w.unit is not None and c.unit is not None
                    ),
                    default=0.0,
                )
                value = cfg.mmr_lambda * base(item) - (1 - cfg.mmr_lambda) * sim
            else:
                value = base(item)
            if value > best_value + 1e-12:
                best_item, best_value = item, value
        chosen.append(best_item[0])
        ids.append(best_item[0].photo.attachment_id)
        remaining.remove(best_item)
    return ids
