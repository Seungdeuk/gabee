"""Baseline v2 평가 세트의 형식·분할 누출·라벨 정책·안전 픽스처 속성과 평가 지표 계산 시험."""

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from app.shared.privacy.types import Kind, Span

API_ROOT = Path(__file__).resolve().parents[4]
V2_DIR = Path(__file__).resolve().parents[1] / "eval" / "baseline_v2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(API_ROOT / "scripts"))
ev = _load("eval_pii_v2_under_test", API_ROOT / "scripts" / "eval_pii_v2.py")
builder = _load("build_baseline_v2_under_test", V2_DIR / "build_baseline_v2.py")


@pytest.fixture(scope="module")
def data():
    return ev.load_splits(V2_DIR)


def _row(**kw):
    base = {
        "id": "a",
        "text": "전화 010-1234-5678",
        "spans": [],
        "known_names": [],
        "tags": [],
        "template_id": "t",
        "split": "train",
    }
    return {**base, **kw}


def _sp(kind, start, end, mask=True, ctx=False):
    return {
        "kind": kind,
        "start": start,
        "end": end,
        "mask_default": mask,
        "context_sensitive": ctx,
    }


def test_dataset_format(data):
    for rows in data.values():
        assert ev.validate_dataset(rows) == []


def test_dataset_size_and_split_ratio(data):
    sizes = {s: len(r) for s, r in data.items()}
    total = sum(sizes.values())
    assert 600 <= total <= 900
    assert 0.55 <= sizes["train"] / total <= 0.65
    assert 0.15 <= sizes["val"] / total <= 0.25
    assert 0.15 <= sizes["test"] / total <= 0.25


def test_negatives_and_tag_coverage(data):
    rows = [r for rs in data.values() for r in rs]
    assert sum(1 for r in rows if not r["spans"]) >= 100
    tags = Counter(t for r in rows for t in r["tags"])
    for tag in (
        "hangul_num",
        "ocr_noise",
        "odd_space",
        "nospace",
        "addr_abbrev",
        "name_no_title",
        "rrn_checksum_fail",
        "card_luhn_fail",
        "multi_pii",
        "long_text",
        "org_name",
        "kin_nickname",
        "alias_title",
        "phone_public",
        "location_general",
    ):
        assert tags[tag] >= 15, tag
    assert all(len(r["text"]) >= 500 for r in rows if "long_text" in r["tags"])
    kinds = {sp["kind"] for r in rows for sp in r["spans"]}
    assert kinds == set(ev.FINE)


def test_no_leakage(data):
    assert ev.check_leakage(data) == []


def test_leakage_is_detected(data):
    train = dict(data["train"][0])
    leaked = {"train": [train], "val": [{**train, "id": "x", "split": "val"}], "test": []}
    problems = ev.check_leakage(leaked)
    assert any("template_id" in p for p in problems)
    assert any("본문 중복" in p for p in problems)


def test_validate_catches_bad_spans():
    assert ev.validate_dataset([_row(spans=[_sp("PHONE_PERSONAL", 3, 99)])])
    overlapping = [_sp("PHONE_PERSONAL", 3, 16), _sp("EMAIL", 10, 16)]
    assert any("겹침" in p for p in ev.validate_dataset([_row(spans=overlapping)]))
    assert any("알 수 없는" in p for p in ev.validate_dataset([_row(spans=[_sp("PHONE", 3, 16)])]))
    missing_policy = [{"kind": "EMAIL", "start": 3, "end": 16}]
    assert any("mask_default" in p for p in ev.validate_dataset([_row(spans=missing_policy)]))


def test_policy_fields_follow_policy(data):
    for rows in data.values():
        for r in rows:
            for sp in r["spans"]:
                assert sp["mask_default"] == builder.MASK_DEFAULT[sp["kind"]]
                value = r["text"][sp["start"] : sp["end"]]
                want = sp["kind"] == "ORGANIZATION" and value.endswith(("병원", "약국", "치과"))
                assert sp["context_sensitive"] == want
    md = builder.MASK_DEFAULT
    assert not md["PHONE_PUBLIC"] and not md["LOCATION"] and not md["ORGANIZATION"]
    assert md["PHONE_PERSONAL"] and md["PERSON_ALIAS"] and md["ADDRESS"]


def test_label_mapping_table():
    assert ev.LEGACY["PHONE_PUBLIC"] == ev.LEGACY["PHONE_PERSONAL"] == "PHONE"
    assert ev.LEGACY["PERSON_ALIAS"] == "PERSON"
    assert ev.LEGACY["LOCATION"] is None and ev.LEGACY["ORGANIZATION"] is None
    assert set(ev.LEGACY) == set(ev.FINE)
    assert ev.assign_fine("PHONE", "1588-1234") == "PHONE_PUBLIC"
    assert ev.assign_fine("PHONE", "080-123-4567") == "PHONE_PUBLIC"
    assert ev.assign_fine("PHONE", "010-0000-1234") == "PHONE_PERSONAL"
    assert ev.assign_fine("PERSON", "김철수") == "PERSON"


def test_builder_is_deterministic_and_profiles_share_structure():
    assert builder.build(True) == builder.build(True)
    safe, private = builder.build(True), builder.build(False)
    for split in safe:
        assert [r["template_id"] for r in safe[split]] == [r["template_id"] for r in private[split]]
    assert safe != private


def test_committed_fixture_matches_generator(data):
    built = builder.build(True)
    for split, rows in built.items():
        assert [r["text"] for r in rows] == [r["text"] for r in data[split]]


def test_safe_fixture_has_no_realistic_identifiers(data):
    rows = [r for rs in data.values() for r in rs]
    assert ev.check_fixture_safety(rows, set(builder.PUBLIC_TEST_PANS)) == []
    assert builder.PUBLIC_TEST_PANS and all(ev._luhn_valid(p) for p in builder.PUBLIC_TEST_PANS)


def test_private_profile_is_not_safe():
    private = [r for rs in builder.build(False).values() for r in rs]
    assert ev.check_fixture_safety(private, set(builder.PUBLIC_TEST_PANS))


def test_safety_check_rejects_realistic_values():
    pans = set(builder.PUBLIC_TEST_PANS)

    def bad(kind, value):
        text = f"값 {value}"
        return ev.check_fixture_safety([_row(text=text, spans=[_sp(kind, 2, len(text))])], pans)

    assert bad("RRN", "900101-1234567")  # 실존 가능한 생년월일
    assert not bad("RRN", "310101-3234567")  # 2031년생: 아직 태어나지 않음
    assert bad("CARD", "4532015112830366")  # 공개 시험 PAN 이 아닌 Luhn 유효 번호
    assert not bad("CARD", "4111111111111111")
    assert not bad("CARD", "4111111111111112")  # Luhn 실패
    assert bad("PHONE_PERSONAL", "010-1234-5678")
    assert not bad("PHONE_PERSONAL", "010-0000-5678")
    assert not bad("PHONE_PERSONAL", "공일공 공공공공 오육칠팔")
    assert bad("EMAIL", "kim@gmail.com") and not bad("EMAIL", "kim@example.com")


def test_detector_accepts_safe_future_rrn(data):
    rows = [r for rs in data.values() for r in rs if "normal_rrn" in r["tags"]]
    assert rows
    for r in rows:
        sp = r["spans"][0]
        found = [(p.kind, p.start, p.end) for p in ev.detect(r["text"], tuple(r["known_names"]))]
        assert (Kind.RRN, sp["start"], sp["end"]) in found


def test_match_exact_vs_overlap():
    gold = [{"start": 0, "end": 10}]
    pred = [{"start": 2, "end": 10}]
    assert ev.match_kind(gold, pred, "exact")[1] == [0]
    pairs, missed, extra = ev.match_kind(gold, pred, "overlap")
    assert pairs == [(0, 0)] and not missed and not extra
    assert ev.match_kind(gold, [{"start": 10, "end": 12}], "overlap")[1] == [
        0
    ]  # 맞닿기만 하면 겹침 아님


def test_score_row_views_and_errors():
    spans = [
        _sp("PHONE_PERSONAL", 3, 16),
        _sp("EMAIL", 17, 20),
        _sp("LOCATION", 21, 24, mask=False),
    ]
    row = _row(text="AAA 010-1234-5678 BBB CCC", spans=spans, tags=["x"], id="r", split="test")
    pred = [Span(Kind.PHONE, 4, 16, 1.0, "t"), Span(Kind.CARD, 0, 3, 1.0, "t")]
    res = ev.score_row(row, pred)
    mp = res["counts"]["mapped"]
    phone = (mp["overlap"]["PHONE"]["tp"], mp["exact"]["PHONE"]["tp"])
    assert phone == (1, 0) and mp["exact"]["PHONE"]["fn"] == 1 and mp["exact"]["PHONE"]["fp"] == 1
    assert mp["overlap"]["EMAIL"]["fn"] == 1 and mp["overlap"]["CARD"]["fp"] == 1
    assert mp["overlap"]["LOCATION"]["fn"] == 1 and mp["overlap"]["LOCATION"]["pred"] == 0
    fine = res["counts"]["fine"]["overlap"]
    assert fine["PHONE_PERSONAL"]["tp"] == 1 and fine["PHONE_PUBLIC"]["gold"] == 0
    kinds = Counter((e["error_type"], e["kind"]) for e in res["errors"])
    assert kinds == {
        ("BOUNDARY", "PHONE"): 1,
        ("FN", "EMAIL"): 1,
        ("FN", "LOCATION"): 1,
        ("FP", "CARD"): 1,
    }
    # 보호 대상(mask_default) 정답은 PHONE·EMAIL 둘, 놓친 것은 EMAIL, 가릴 필요 없는 예측은 CARD 하나
    assert res["policy"] == {"protect_gold": 2, "protect_hit": 1, "pred": 2, "overmask": 1}


def test_alias_and_public_phone_label_views():
    row = _row(
        text="지우 엄마 1588-1234",
        spans=[_sp("PERSON_ALIAS", 0, 5), _sp("PHONE_PUBLIC", 6, 15, mask=False)],
    )
    pred = [Span(Kind.PERSON, 0, 2, 1.0, "t"), Span(Kind.PHONE, 6, 15, 1.0, "t")]
    res = ev.score_row(row, pred)
    fine = res["counts"]["fine"]["overlap"]
    assert fine["PERSON_ALIAS"]["fn"] == 1 and fine["PERSON"]["fp"] == 1  # 세분 라벨로는 틀림
    assert fine["PHONE_PUBLIC"]["tp"] == 1
    assert res["counts"]["mapped"]["overlap"]["PERSON"]["tp"] == 1  # 기존 Kind 로 접으면 맞음
    assert res["policy"]["overmask"] == 1  # 공개번호를 가린 것은 과마스킹


def test_aggregate_and_fpr():
    def rec(tp, fp, fn, flagged, gold):
        c = {
            v: {m: {k: ev.new_counts() for k in ev.VIEW_KINDS[v]} for m in ev.MODES}
            for v in ev.VIEW_KINDS
        }
        c["mapped"]["overlap"]["PHONE"].update(tp=tp, fp=fp, fn=fn, gold=tp + fn, pred=tp + fp)
        return {"counts": c, "flagged": flagged, "n_gold": gold}

    recs = [rec(3, 1, 1, True, 4), rec(0, 0, 0, False, 0), rec(0, 1, 0, True, 0)]
    m = ev.aggregate(recs, "mapped", "overlap", ["PHONE"])
    assert m["precision"] == pytest.approx(3 / 5) and m["recall"] == pytest.approx(3 / 4)
    assert m["f1"] == pytest.approx(2 * 0.6 * 0.75 / 1.35) and m["fnr"] == pytest.approx(0.25)
    assert ev.fpr_of(recs) == {"neg_sentences": 2, "neg_flagged": 1, "fpr": 0.5}


def test_percentile():
    assert ev.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert ev.percentile([], 0.95) == 0.0
