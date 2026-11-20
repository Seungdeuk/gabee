"""추억 후보 그룹화(PR5) 순수 알고리즘 시험: 합성 임베딩·시각만 쓰고 DB·모델·네트워크가 필요 없다. 정확도(정답 라벨 평가)는 `scripts/grouping_synthetic_eval.py` 가 따로 잰다."""

import io
import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image, ImageFilter

from app.features.family_memory import grouping as g
from app.features.family_memory import quality

T0 = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
DIM = 32


def topic(seed: int) -> tuple[float, ...]:
    rng = random.Random(f"topic-{seed}")
    return tuple(rng.gauss(0, 1) for _ in range(DIM))


def near(base: tuple[float, ...], seed: str, noise: float = 0.5) -> tuple[float, ...]:
    rng = random.Random(seed)
    unit = math.sqrt(sum(v * v for v in base))
    return tuple(v / unit + rng.gauss(0, noise / math.sqrt(DIM)) for v in base)


def photo(
    pid: str,
    minutes: float | None,
    topic_id: int | None = 1,
    *,
    group="fam1",
    batch=None,
    day_offset: float = 0,
    uploaded=T0,
    **kw,
) -> g.PhotoFeatures:
    taken = None if minutes is None else T0 + timedelta(days=day_offset, minutes=minutes)
    emb = None if topic_id is None else near(topic(topic_id), pid)
    return g.PhotoFeatures(
        attachment_id=pid,
        group_id=group,
        uploader_id="u1",
        uploaded_at=uploaded,
        taken_at=taken,
        batch_id=batch,
        embedding=kw.pop("embedding", emb),
        **kw,
    )


def burst(prefix: str, n: int, start_min: float = 0, step: float = 5, topic_id: int = 1, **kw):
    return [photo(f"{prefix}{i:02d}", start_min + i * step, topic_id, **kw) for i in range(n)]


def ids(candidates):
    return [sorted(c.attachment_ids) for c in candidates]


# ---------- 1·2. 같은 시점 그룹화, 다른 날짜·연도 분리 ----------
def test_similar_photos_at_the_same_time_form_one_candidate():
    result = g.group_photos(burst("a", 5))
    assert len(result) == 1 and sorted(result[0].attachment_ids) == [f"a{i:02d}" for i in range(5)]
    c = result[0]
    assert c.algorithm_version == g.ALGORITHM_VERSION and 0 < c.score <= 1
    assert c.time_evidence.basis == "taken_at" and c.time_evidence.dated_count == 5
    assert (
        c.representative_id in c.attachment_ids and c.representative_id == c.representative_ids[0]
    )


def test_the_same_scene_in_different_years_is_never_merged():
    photos = burst("y23", 4, topic_id=1, day_offset=-365) + burst("y24", 4, topic_id=1)
    result = g.group_photos(photos)
    assert len(result) == 2
    for c in result:
        assert {a[:3] for a in c.attachment_ids} in ({"y23"}, {"y24"})


def test_the_same_scene_a_few_days_apart_is_separate_but_overnight_is_bridged_when_similar():
    two_days = burst("d1", 4, topic_id=1) + burst("d3", 4, topic_id=1, day_offset=2)
    assert len(g.group_photos(two_days)) == 2  # 간격이 bridge_hours(36h)를 넘는다
    overnight = burst("n1", 4, 0, topic_id=1) + burst("n2", 4, 60 * 22, topic_id=1)  # 약 20시간 뒤
    result = g.group_photos(overnight)
    assert len(result) == 1 and result[0].time_evidence.bridged is True
    other_scene = burst("n1", 4, 0, topic_id=1) + burst("n2", 4, 60 * 22, topic_id=2)
    assert len(g.group_photos(other_scene)) == 2  # 이미지가 다르면 잇지 않는다


def test_different_events_on_the_same_day_are_split_by_image_and_time():
    photos = burst("am", 4, 0, topic_id=1) + burst(
        "pm", 4, 60 * 3, topic_id=2
    )  # 3시간 뒤 다른 장면
    result = g.group_photos(photos)
    assert len(result) == 2
    assert {frozenset(a[:2] for a in c.attachment_ids) for c in result} == {
        frozenset({"am"}),
        frozenset({"pm"}),
    }


def test_a_burst_stays_together_even_if_images_differ_within_the_soft_gap():
    photos = [photo(f"b{i}", i * 2, topic_id=1 if i % 2 == 0 else 2) for i in range(6)]
    assert len(g.group_photos(photos)) == 1  # 30분 안의 연사는 이미지가 달라도 한 장면


# ---------- 3. batch_id 경계 ----------
def test_a_batch_id_alone_never_merges_dated_photos_into_one_event():
    early = burst("e", 4, 0, topic_id=1, batch="batch-0001")
    late = burst("l", 4, 0, topic_id=1, batch="batch-0001", day_offset=40)
    result = g.group_photos(early + late)
    assert len(result) == 2  # 같이 올렸지만 촬영일이 40일 차이: 같은 사건이라 단정하지 않는다


def test_undated_photos_join_only_via_a_batch_with_dated_siblings_in_one_group_and_similar_images():
    dated = burst("d", 4, 0, topic_id=1, batch="trip-batch-1")
    joined = photo("u1", None, 1, batch="trip-batch-1")
    dissimilar = photo("u2", None, 2, batch="trip-batch-1")
    no_batch = photo("u3", None, 1)
    other_batch = photo("u4", None, 1, batch="other-batch-9")
    no_embedding = photo("u5", None, None, batch="trip-batch-1")
    [c] = g.group_photos([*dated, joined, dissimilar, no_batch, other_batch, no_embedding])
    assert "u1" in c.attachment_ids
    for excluded in ("u2", "u3", "u4", "u5"):
        assert excluded not in c.attachment_ids
    assert c.time_evidence.batch_attached_count == 1 and c.time_evidence.dated_count == 4
    assert c.attachment_ids[-1] == "u1"  # 날짜 없는 사진은 뒤에


def test_undated_photo_is_not_attached_when_its_batch_is_split_across_groups():
    a = burst("a", 4, 0, topic_id=1, batch="split-batch")
    b = burst("b", 4, 0, topic_id=1, batch="split-batch", day_offset=30)
    undated = photo("u1", None, 1, batch="split-batch")
    result = g.group_photos([*a, *b, undated])
    assert all("u1" not in c.attachment_ids for c in result)  # 어느 그룹인지 근거가 모호하다


# ---------- 4·8. 촬영 시각 누락, 업로드 시각을 촬영 시각으로 쓰지 않음 ----------
def test_no_taken_at_means_no_group_even_if_uploaded_together():
    photos = [photo(f"u{i}", None, 1, batch="same-upload", uploaded=T0) for i in range(6)]
    assert g.group_photos(photos) == []  # 업로드 시각을 촬영 시각이라 단정하지 않는다


def test_upload_time_is_not_used_as_event_time():
    same_upload = [photo(f"o{i}", i * 5, 1, day_offset=-400, uploaded=T0) for i in range(4)] + [
        photo(f"n{i}", i * 5, 1, uploaded=T0) for i in range(4)
    ]
    result = g.group_photos(same_upload)
    assert len(result) == 2  # 같은 순간에 올렸지만 촬영 연도가 다르다
    assert {c.time_evidence.start.year for c in result} == {2023, 2024}


def test_photos_with_only_time_evidence_still_group_but_with_neutral_image_cohesion():
    photos = [photo(f"t{i}", i * 10, None) for i in range(4)]
    [c] = g.group_photos(photos)
    assert len(c.attachment_ids) == 4


# ---------- 5. 중복 ----------
def test_exact_and_near_duplicates_are_detected_and_never_deleted():
    photos = burst("p", 4, 0, topic_id=1)
    exact_a = photo("x1", 50, 1, content_hash="same-bytes", sharpness=0.9, exposure=0.8)
    exact_b = photo("x2", 51, 1, content_hash="same-bytes", sharpness=0.4, exposure=0.8)
    hash_a = photo("h1", 52, 1, dhash=0b1011 << 20, sharpness=0.7, exposure=0.7)
    hash_b = photo("h2", 53, 1, dhash=(0b1011 << 20) ^ 0b11, sharpness=0.6, exposure=0.7)
    [c] = g.group_photos([*photos, exact_a, exact_b, hash_a, hash_b])
    assert dict(c.duplicates) == {"x2": "x1", "h2": "h1"}  # 더 나은 한 장만 남긴다
    assert {"x1", "x2", "h1", "h2"} <= set(c.attachment_ids)  # 원본 목록에는 모두 남아 있다
    assert c.representative_id not in {"x2", "h2"}


def test_near_duplicate_by_embedding_and_all_duplicate_groups_make_no_candidate():
    base = topic(1)
    same = [
        g.PhotoFeatures(f"c{i}", "fam1", "u1", T0, T0 + timedelta(minutes=i), embedding=base)
        for i in range(4)
    ]
    assert g.group_photos(same) == []  # 4장이지만 고유한 장면은 1장 → 추억 후보가 아니다
    unique = burst("u", 3, 0)
    copy = g.PhotoFeatures(
        "u-copy", "fam1", "u1", T0, T0 + timedelta(minutes=30), embedding=unique[0].embedding
    )
    [c] = g.group_photos([*unique, copy])
    assert (
        dict(c.duplicates) == {"u-copy": "u00"} and len(c.attachment_ids) == 4
    )  # 임베딩이 같은 사진은 중복 후보


def test_duplicates_reduce_a_scenes_weight_in_representative_selection():
    cfg = g.GroupingConfig(max_representatives=1)
    popular = [
        photo(f"pop{i}", i, 1, content_hash="cp", sharpness=0.9, exposure=0.9) for i in range(5)
    ]
    single = photo("single", 20, 1, sharpness=0.9, exposure=0.9)
    others = burst("o", 3, 30, topic_id=1)
    [c] = g.group_photos([*popular, single, *others], cfg)
    assert c.representative_id == "single"  # 같은 화질이면 중복이 많은 장면보다 한 장짜리를 고른다
    assert c.representative_id not in {d for d, _ in c.duplicates}


# ---------- 6. 대표 사진 ----------
def test_representative_prefers_sharp_well_exposed_and_central_photos():
    photos = burst("q", 5, 0, topic_id=1)
    blurry = photo("blurry", 30, 1, sharpness=0.02, exposure=0.9)
    dark = photo("dark", 31, 1, sharpness=0.9, exposure=0.05)
    best = photo("best", 32, 1, sharpness=0.95, exposure=0.95)
    [c] = g.group_photos([*photos, blurry, dark, best])
    assert c.representative_id == "best"
    assert "blurry" not in c.representative_ids[:1] and "dark" not in c.representative_ids[:1]


def test_second_representative_is_diverse_not_a_near_copy():
    cfg = g.GroupingConfig(max_representatives=2, mmr_lambda=0.5)
    scene_a = [photo(f"A{i}", i, 1, sharpness=0.9, exposure=0.9) for i in range(3)]
    scene_b = [photo(f"B{i}", 100 + i, 2, sharpness=0.6, exposure=0.8) for i in range(2)]
    [c] = g.group_photos(
        [*scene_a, *scene_b], g.GroupingConfig(**{**cfg.__dict__, "split_cos": -1.0})
    )
    first, second = c.representative_ids
    assert first[0] != second[0]  # 첫 대표와 같은 장면(A)이 아니라 다른 장면(B)에서 고른다


# ---------- 7. 가족 격리 ----------
def test_families_are_processed_separately_and_never_mixed():
    a = burst("a", 4, group="fam1")
    b = burst("b", 4, group="fam2")
    result = g.group_photos([*a, *b])
    assert len(result) == 2
    for c in result:
        assert all(i.startswith("a" if c.group_id == "fam1" else "b") for i in c.attachment_ids)
    assert len({c.candidate_id for c in result}) == 2
    # 같은 시각·같은 임베딩이어도(같은 batch_id 라도) 가족이 다르면 섞이지 않는다
    mixed = [photo(f"m{i}", i, 1, group="fam1", batch="shared-bat") for i in range(3)] + [
        photo(f"n{i}", i, 1, group="fam2", batch="shared-bat") for i in range(3)
    ]
    assert sorted(len(c.attachment_ids) for c in g.group_photos(mixed)) == [3, 3]


# ---------- 10·11. 빈 결과, 입력 순서, 결정성 ----------
def test_not_enough_photos_gives_an_empty_result():
    assert g.group_photos([]) == []
    assert g.group_photos(burst("a", 2)) == []
    assert g.group_photos([photo("x", 0, 1), photo("y", 60 * 50, 1), photo("z", 60 * 100, 1)]) == []


def test_result_is_identical_for_any_input_order():
    photos = (
        burst("a", 5, 0, topic_id=1)
        + burst("b", 4, 60 * 4, topic_id=2)
        + burst("c", 4, 0, topic_id=1, day_offset=-400)
        + [photo("dup1", 61, 1, content_hash="h"), photo("dup2", 62, 1, content_hash="h")]
        + [photo("u1", None, 1, batch="bt-xxxxxxx")]
        + burst("g", 4, 0, group="fam2")
    )
    expected = g.group_photos(photos)
    assert len(expected) >= 3
    rng = random.Random(7)
    for _ in range(25):
        shuffled = photos[:]
        rng.shuffle(shuffled)
        assert g.group_photos(shuffled) == expected
    assert g.group_photos(photos + photos[:3]) == expected  # 같은 id 가 겹쳐 들어와도 같다


def test_candidate_output_has_no_place_person_or_emotion_fields():
    names = {f for f in g.MemoryCandidate.__dataclass_fields__}
    assert names == {
        "candidate_id",
        "group_id",
        "attachment_ids",
        "representative_id",
        "representative_ids",
        "duplicates",
        "time_evidence",
        "score",
        "algorithm_version",
    }
    assert {f for f in g.TimeEvidence.__dataclass_fields__} == {
        "basis",
        "start",
        "end",
        "dated_count",
        "batch_attached_count",
        "bridged",
    }


@pytest.mark.parametrize(
    "bad",
    [
        (float("nan"),) * DIM,
        (0.0,) * DIM,
        (1.0, 2.0),
        (),
        None,
        (float("inf"),) + (0.0,) * (DIM - 1),
    ],
)
def test_invalid_embeddings_are_ignored_instead_of_crashing(bad):
    photos = [photo(f"v{i}", i * 5, 1) for i in range(4)] + [photo("bad", 25, 1, embedding=bad)]
    [c] = g.group_photos(photos)
    assert "bad" in c.attachment_ids  # 이미지 근거만 없고 시간 근거로 합류한다
    assert all(math.isfinite(c.score) for c in [c])


def test_naive_datetimes_are_treated_as_utc_and_mixed_timezones_compare_correctly():
    from datetime import timezone

    kst = timezone(timedelta(hours=9))
    photos = [
        g.PhotoFeatures("t1", "fam1", "u", T0, taken_at=datetime(2024, 5, 1, 10, 0)),  # naive = UTC
        g.PhotoFeatures("t2", "fam1", "u", T0, taken_at=datetime(2024, 5, 1, 19, 5, tzinfo=kst)),
        g.PhotoFeatures("t3", "fam1", "u", T0, taken_at=datetime(2024, 5, 1, 10, 10, tzinfo=UTC)),
    ]
    [c] = g.group_photos(photos)
    assert c.time_evidence.start == T0 and c.time_evidence.end == T0 + timedelta(minutes=10)


# ---------- 화질·해시 ----------
def _jpeg(img: Image.Image, quality=90) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def _textured(seed=0, size=300) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("L", (size, size))
    img.putdata([rng.randrange(256) for _ in range(size * size)])
    return img.convert("RGB")


def test_image_stats_rank_sharp_over_blurry_and_good_over_bad_exposure():
    sharp = quality.image_stats(_jpeg(_textured()))
    blurry = quality.image_stats(_jpeg(_textured().filter(ImageFilter.GaussianBlur(8))))
    dark = quality.image_stats(_jpeg(Image.new("RGB", (200, 200), (3, 3, 3))))
    white = quality.image_stats(_jpeg(Image.new("RGB", (200, 200), (254, 254, 254))))
    mid = quality.image_stats(_jpeg(Image.new("RGB", (200, 200), (128, 128, 128))))
    assert sharp.sharpness > blurry.sharpness + 0.3
    assert mid.exposure > 0.8 > dark.exposure and mid.exposure > white.exposure
    assert all(0 <= s.sharpness <= 1 and 0 <= s.exposure <= 1 for s in (sharp, blurry, dark, white))


def test_image_hashes_detect_exact_and_recompressed_copies_but_not_other_scenes():
    base = _textured(1)
    data = _jpeg(base, 95)
    same = quality.image_stats(data)
    assert quality.image_stats(data).content_hash == same.content_hash
    recompressed = quality.image_stats(_jpeg(Image.open(io.BytesIO(data)), 60))
    resized = quality.image_stats(_jpeg(base.resize((150, 150)), 85))
    other = quality.image_stats(_jpeg(_textured(2)))
    assert recompressed.content_hash != same.content_hash
    assert (
        g._hamming(recompressed.dhash, same.dhash) <= 6
        and g._hamming(resized.dhash, same.dhash) <= 12
    )
    assert g._hamming(other.dhash, same.dhash) > 12


def test_unreadable_image_gives_no_stats():
    assert quality.image_stats(b"not an image") is None
