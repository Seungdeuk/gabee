"""독립 검토에서 나온 문제의 회귀 시험: 정규식 폭주(ReDoS), 토큰 위조·변형, 계좌 문맥, 점수 임계값, 복원 범위 등."""

import json
import random
import time
from pathlib import Path

import pytest

from app.shared.privacy import (
    ANALYSIS,
    REPLY,
    Action,
    Kind,
    Policy,
    Pseudonymizer,
    Span,
    detect,
    prepare_transcript,
    restore_json,
    restore_value,
)
from app.shared.privacy.detectors import _luhn_ok

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"


def kinds(text, names=()):
    return {s.kind for s in detect(text, names)}


def timed(fn, *args):
    start = time.perf_counter()
    fn(*args)
    return time.perf_counter() - start


# ---------- 1. 정규식 폭주 ----------
HOSTILE = {
    "open-phone-spaces": "[PHONE" + " " * 100_000 + "_",
    "open-spaces": "[" + " " * 100_000,
    "underscore-spaces": "[PHONE" + "_ " * 50_000,
    "many-open": "[[[[" * 25_000,
    "fullwidth-open": "【PHONE" + " " * 100_000,
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_restore_is_linear_on_hostile_input(name):
    text = HOSTILE[name]
    pz = Pseudonymizer()
    pz.apply("010-1234-5678", ANALYSIS)
    assert timed(pz.restore, text) < 0.5


REPEATED = {
    "digits": "1" * 200_000,
    "dot": "a." * 100_000,
    "hyphen": "1-" * 100_000,
    "latin": "a" * 200_000,
    "spaces": " " * 200_000,
    "hangul": "가" * 200_000,
    "secret-kw": "비번 " * 60_000,
}


@pytest.mark.parametrize("name", list(REPEATED))
def test_detect_is_fast_on_repeated_input(name):
    text = REPEATED[name]
    assert timed(detect, text, ("김민수",)) < 1.5


def test_detect_scales_linearly():
    small = timed(detect, "a." * 20_000)
    large = timed(detect, "a." * 160_000)
    assert large < max(small, 0.005) * 40  # 8배 입력에 40배 이내(제곱이면 64배 이상)


def test_neutralize_is_linear_too():
    pz = Pseudonymizer()
    assert timed(pz.apply, "[PHONE" + " " * 100_000, ANALYSIS) < 1.5


# ---------- 3. 토큰 위조·변형·이중 복원 ----------
def test_user_written_token_variants_are_neutralized():
    pz = Pseudonymizer()
    r = pz.apply(
        "[phone_1] [PHONE_1 ] [PHONE_01] 【PHONE_1】 ［PHONE_1］ 진짜 010-1234-5678", ANALYSIS
    )
    assert r.text.count("[PHONE_1]") == 1
    out = pz.restore(r.text)
    assert out.text.count("010-1234-5678") == 1
    assert out.unknown_tokens == []  # 위조 글자는 이미 ‹ › 로 무력화되어 토큰 후보가 아니다


def test_fullwidth_and_variant_tokens_from_model_are_reported_not_restored():
    pz = Pseudonymizer()
    pz.apply("010-1234-5678", ANALYSIS)
    out = pz.restore("【PHONE_1】 ［PHONE_1］ [phone_1] [PHONE_1 ] [PHONE_01] [PHONE_１] [PHONE_1]")
    assert out.text.count("010-1234-5678") == 1
    assert out.unknown_tokens == [
        "【PHONE_1】",
        "［PHONE_1］",
        "[phone_1]",
        "[PHONE_1 ]",
        "[PHONE_01]",
        "[PHONE_１]",
    ]


def test_token_shaped_speaker_or_known_name_cannot_be_restored_twice():
    prep = prepare_transcript(
        [(1, "[PHONE_1]", "응"), (2, "김민수", "안녕")], ["[PHONE_1]", "김민수"], REPLY
    )
    first = restore_value(prep, "[PERSON_1] 이 말함")
    assert first.value == "‹PHONE_1› 이 말함"
    assert (
        restore_value(prep, first.value).value == first.value
    )  # 두 번째 복원은 아무것도 바꾸지 않는다


def test_restore_json_handles_keys_tuples_sets():
    prep = prepare_transcript([(1, "김민수", "안녕")], ["김민수"], ANALYSIS)
    out = restore_json(
        prep, {"[PERSON_1]": ("[PERSON_1]", 3), "s": {"[PERSON_1]"}, "u": ["[PERSON_7]"]}
    )
    assert out.value == {"김민수": ("김민수", 3), "s": {"김민수"}, "u": ["[PERSON_7]"]}
    assert out.unknown_tokens == ["[PERSON_7]"]


def test_span_repr_hides_canonical():
    (span,) = detect("민수야", ("김민수",))
    assert "김민수" not in repr(span)
    assert Span(Kind.PERSON, 0, 1, 0.5, "x", "김민수").canonical == "김민수"


# ---------- 9. 복원 범위 ----------
def test_restore_kinds_generalize_unrestorable_tokens():
    rows = [
        (1, "김민수", "내 번호 010-1234-5678 메일 kim@example.com 집 서울시 강남구 테헤란로 152")
    ]
    with prepare_transcript(rows, ["김민수"], ANALYSIS) as prep:
        text = "[PERSON_1] [PHONE_1] [EMAIL_1] [ADDR_1] [PHONE_9]"
        out = restore_value(prep, text)
        assert out.value == "김민수 (연락처) (이메일) 서울시 강남구 테헤란로 152 [PHONE_9]"
        assert out.generalized_tokens == ["[PHONE_1]", "[EMAIL_1]"]
        assert out.unknown_tokens == ["[PHONE_9]"]
        assert (
            restore_value(prep, "[PHONE_9]", generalize_unknown=True).value == "(알 수 없는 항목)"
        )
    with prepare_transcript(rows, ["김민수"], REPLY) as prep:
        assert restore_value(prep, "[PERSON_1] [ADDR_1]").value == "김민수 (주소)"


def test_restore_kinds_never_leak_through_json():
    rows = [(1, "김민수", "번호 010-1234-5678")]
    with prepare_transcript(rows, [], ANALYSIS) as prep:
        out = restore_json(prep, {"summary": "[PHONE_1] 로 연락"})
        assert "010-1234-5678" not in json.dumps(out.value, ensure_ascii=False)


def test_kinship_speaker_not_tokenized():
    rows = [(1, "엄마", "엄마가 말했잖아"), (2, "김민수", "엄마 어디야")]
    with prepare_transcript(rows, ["엄마", "김민수"], ANALYSIS) as prep:
        assert [line.speaker for line in prep.lines] == ["엄마", "[PERSON_1]"]
        assert prep.lines[0].text == "엄마가 말했잖아"


# ---------- 4. 계좌 문맥 ----------
@pytest.mark.parametrize(
    "text",
    [
        "우체국 택배 운송장 번호 6012345678901 이야",
        "우체국 등기 1234567890123 조회해봐",
        "카카오 선물하기 주문번호 202611030012 로 조회해봐",
        "카카오택시 예약번호 1234567890 이야",
        "국민 10명 중 9명이 1234567890 번",
        "기업 공시 번호 1234567890",
        "IBK 앱 오류코드 1234567890",
        "농협 앞에서 2026-11-03 10:30에 보자",
    ],
)
def test_account_false_positive_regressions(text):
    assert Kind.ACCOUNT not in kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "국민은행 123456-01-123456 입금해줘",
        "국민 123456-01-123456",
        "신한 110123456789 로 보내",
        "계좌번호 1002345678901 야",
        "3333-12-3456789 카카오뱅크로 보내",
        "1002-345-678901 (우리)",
        "카카오뱅크 3333-12-3456789",
    ],
)
def test_real_accounts_still_detected(text):
    assert Kind.ACCOUNT in kinds(text)


# ---------- 5. 점수 임계값 ----------
def random_numbers(length, count=2000, seed=7):
    rng = random.Random(seed)
    return ["".join(str(rng.randrange(10)) for _ in range(length)) for _ in range(count)]


@pytest.mark.parametrize("length", [13, 14, 16])
@pytest.mark.parametrize("template", ["번호 {} 이야", "운송장 {} 이야"])
def test_random_long_numbers_are_rarely_blocked(length, template):
    blocked = 0
    nums = random_numbers(length)
    for d in nums:
        with Pseudonymizer() as pz:
            blocked += pz.apply(template.format(d), ANALYSIS).blocked
    assert blocked / len(nums) < 0.01


def test_low_score_high_risk_is_masked_not_blocked_and_not_restorable():
    pz = Pseudonymizer()
    # 하이픈 없는 13자리 + 체크섬 불일치 = 낮은 점수 RRN
    r = pz.apply("번호 9001011234567 이야", ANALYSIS)
    assert not r.blocked and r.text == "번호 [RRN] 이야" and r.counts_by_kind == {"RRN": 1}
    assert pz.size == 0


def test_strong_high_risk_stays_blocked():
    def luhn16():
        body = "453914880343646"
        return body + next(c for c in "0123456789" if _luhn_ok(body + c))

    pz = Pseudonymizer()
    assert pz.apply(
        f"카드 {luhn16()[:4]}-{luhn16()[4:8]}-{luhn16()[8:12]}-{luhn16()[12:]}", ANALYSIS
    ).blocked
    assert pz.apply("비번 abcd1234", ANALYSIS).blocked
    assert (
        pz.apply("주민번호 900101-1234567", ANALYSIS).blocked is False
    )  # 체크섬 불일치 + 하이픈 = 0.6
    valid = "9001011234568"  # 체크섬이 맞는 합성 번호
    assert pz.apply(f"주민번호 {valid[:6]}-{valid[6:]}", ANALYSIS).blocked
    assert Policy("x", {Kind.PHONE: Action.BLOCK}).block_min_score == 0.7


# ---------- 6. 이름 별칭 ----------
@pytest.mark.parametrize(
    "text,names",
    [
        ("하나도 안 먹었어", ("김하나",)),
        ("수정 좀 해줘, 수정이 필요해", ("이수정",)),
        ("이거 보라고!", ("박보라",)),
        ("더 나은 방법 없을까", ("이나은",)),
        ("지원 신청 마감이 내일이야", ("김지원",)),
    ],
)
def test_alias_common_words_not_masked_but_full_name_is(text, names):
    assert Kind.PERSON not in kinds(text, names)
    assert Kind.PERSON in kinds(f"{names[0]}가 왔어", names)


def test_neighbour_particle_ne():
    assert Kind.PERSON in kinds("민수네 집에 갔어", ("김민수",))


# ---------- 7. 기타 오탐·미탐 ----------
@pytest.mark.parametrize(
    "text",
    [
        "하나님 감사합니다", "박사님이 그러는데", "형수님 오신대", "목사님 말씀", "변호사님 연락 왔어", "부처님 오신 날",
        "올레길 7코스 걷자", "산책로 2바퀴 돌았어", "서울 대도시라 복잡해", "경기 신도시로 이사 갈까", "3동 2호선 타고 와",
        "비번 wifi 랑 같아",
    ],
)  # fmt: skip
def test_misc_false_positive_regressions(text):
    assert detect(text) == []


@pytest.mark.parametrize(
    "text,kind",
    [
        ("연락처 010–1234–5678", Kind.PHONE),
        ("０１０-１２３４-５６７８", Kind.PHONE),
        ("010)1234-5678", Kind.PHONE),
        ("010/1234/5678", Kind.PHONE),
        ("주민번호 900101 - 1234567", Kind.RRN),
        ("부산 동구 좌천동 123-4", Kind.ADDRESS),
        ("서울시 중구 세종대로 110", Kind.ADDRESS),
    ],
)
def test_variants_now_detected(text, kind):
    assert kind in kinds(text)


def test_fullwidth_span_positions_match_original():
    text = "번호 ０１０-１２３４-５６７８ 야"
    (span,) = detect(text)
    assert text[span.start : span.end] == "０１０-１２３４-５６７８"


# ---------- 10. 데이터셋 ----------
def test_datasets_use_reserved_email_domains_only():
    reserved = ("example.com", "example.org", "example.net", ".test", ".example", ".invalid")
    for name in ("pii_eval.jsonl", "pii_eval_holdout.jsonl"):
        for line in (EVAL_DIR / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for s in row["spans"]:
                if s["kind"] == "EMAIL" and "@" in row["text"][s["start"] : s["end"]]:
                    domain = row["text"][s["start"] : s["end"]].rsplit("@", 1)[1].strip().lower()
                    assert domain.endswith(reserved) or domain == "example", (name, domain)


def test_holdout_dataset_shape():
    rows = [
        json.loads(x)
        for x in (EVAL_DIR / "pii_eval_holdout.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) >= 80
    assert any(not r["spans"] for r in rows) and any(r["spans"] for r in rows)
