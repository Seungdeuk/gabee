"""근거 목록·문장 검증기 시험. 외부 의존 없는 순수 함수만 다룬다."""

import dataclasses
import unicodedata
from datetime import date

import pytest

from app.features.weekly_news.evidence import (
    FALLBACK_TITLE,
    MAX_ITEMS,
    MAX_TEXT,
    Failed,
    Source,
    SourceRecord,
    Validated,
    build_sources,
    validate,
)


def rec(kind, ref, title, day, start_time=None):
    return SourceRecord(kind=kind, ref=ref, title=title, day=day, start_time=start_time)


D10 = date(2026, 11, 10)
D11 = date(2026, 11, 11)
D09 = date(2026, 11, 9)

RECORDS = [
    rec("event", "ev-b", "치과 예약", D11, "09:00"),
    rec("event", "ev-a", "학교 공연", D10, "14:30"),
    rec("todo", "td-1", "장보기", D09),
    rec("document", "doc-1", "가정통신문 11월", D10),
    rec("todo", "td-2", "분리수거", D11),
]


@pytest.fixture
def sources():
    return build_sources(RECORDS)


def by_id(sources, sid):
    return next(s for s in sources if s.id == sid)


def cand(items, title="이번 주 정리"):
    return {"title": title, "items": [{"text": t, "source_ids": ids} for t, ids in items]}


def ok(result):
    assert isinstance(result, Validated), result
    return result


# ── build_sources ─────────────────────────────────────────────


def test_time_less_records_sort_before_timed_on_same_day(sources):
    # 시간 없는 기록은 같은 날 시간 있는 기록보다 앞(종일 취급)
    assert [s.id for s in sources] == ["t1", "d1", "e1", "t2", "e2"]


def test_ids_are_per_kind_sequences_in_sorted_order(sources):
    assert [s.id for s in sources if s.kind == "event"] == ["e1", "e2"]
    assert [s.id for s in sources if s.kind == "todo"] == ["t1", "t2"]
    assert [s.id for s in sources if s.kind == "document"] == ["d1"]
    assert by_id(sources, "e1").ref == "ev-a"  # 더 이른 약속이 e1
    assert by_id(sources, "e2").ref == "ev-b"


def test_same_input_same_ids_and_order():
    assert build_sources(RECORDS) == build_sources(RECORDS)


def test_input_order_does_not_matter():
    assert build_sources(list(reversed(RECORDS))) == build_sources(RECORDS)
    shuffled = [RECORDS[3], RECORDS[0], RECORDS[4], RECORDS[2], RECORDS[1]]
    assert build_sources(shuffled) == build_sources(RECORDS)


def test_same_day_same_time_ties_broken_by_ref():
    a = rec("event", "z-ref", "가", D10, "10:00")
    b = rec("event", "a-ref", "나", D10, "10:00")
    got = build_sources([a, b])
    assert [(s.id, s.ref) for s in got] == [("e1", "a-ref"), ("e2", "z-ref")]


def test_build_empty():
    assert build_sources([]) == []


def test_duplicate_kind_ref_is_collapsed():
    r = rec("event", "ev-a", "학교 공연", D10, "14:30")
    got = build_sources([r, r])
    assert [s.id for s in got] == ["e1"]


def test_same_ref_different_kind_both_kept():
    got = build_sources(
        [rec("event", "x1", "가", D10, "09:00"), rec("todo", "x1", "나", D10, "09:00")]
    )
    assert sorted(s.id for s in got) == ["e1", "t1"]


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        build_sources([rec("memo", "m", "메모", D10)])


def test_source_fields(sources):
    e1 = by_id(sources, "e1")
    assert (e1.kind, e1.ref, e1.label, e1.date, e1.time) == (
        "event",
        "ev-a",
        "학교 공연",
        D10,
        "14:30",
    )
    t1 = by_id(sources, "t1")
    assert t1.time is None


def test_label_whitespace_normalized():
    got = build_sources([rec("event", "a", "  치과 \n  예약  ", D10)])
    assert got[0].label == "치과 예약"


def test_source_has_no_memo_place_or_body_fields():
    names = {f.name for f in dataclasses.fields(Source)}
    assert names == {"id", "kind", "ref", "label", "date", "time"}
    rec_names = {f.name for f in dataclasses.fields(SourceRecord)}
    assert rec_names == {"kind", "ref", "title", "day", "start_time"}


def test_source_is_immutable(sources):
    with pytest.raises(dataclasses.FrozenInstanceError):
        sources[0].label = "x"


# ── validate: 근거 id ─────────────────────────────────────────


def test_valid_sentence_kept(sources):
    r = ok(validate(cand([("학교 공연이 있었어요", ["e1"])]), sources, set()))
    assert r.title == "이번 주 정리"
    assert [(i.text, i.source_ids) for i in r.items] == [("학교 공연이 있었어요", ("e1",))]
    assert [s.id for s in r.used_sources] == ["e1"]


def test_empty_source_ids_dropped(sources):
    r = ok(
        validate(
            cand([("근거 없는 문장", []), ("학교 공연이 있었어요", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [i.text for i in r.items] == ["학교 공연이 있었어요"]


def test_unknown_id_among_valid_ones_drops_sentence(sources):
    r = ok(
        validate(
            cand([("혼합 인용", ["e1", "e99"]), ("학교 공연이 있었어요", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [i.text for i in r.items] == ["학교 공연이 있었어요"]
    assert [s.id for s in r.used_sources] == ["e1"]


def test_ids_are_case_and_space_sensitive(sources):
    for bad in ("E1", " e1", "e1 ", "e01", "x1"):
        r = validate(cand([("문장", [bad])]), sources, set())
        assert isinstance(r, Failed)


def test_source_ids_wrong_types_dropped(sources):
    c = {
        "title": "제목",
        "items": [
            {"text": "정수 id", "source_ids": [1]},
            {"text": "문자열 하나", "source_ids": "e1"},
            {"text": "None", "source_ids": None},
            {"text": "누락"},
            {"text": "정상", "source_ids": ["e1"]},
        ],
    }
    r = ok(validate(c, sources, set()))
    assert [i.text for i in r.items] == ["정상"]


def test_duplicate_source_ids_in_one_item_collapsed(sources):
    r = ok(validate(cand([("학교 공연", ["e1", "e1"])]), sources, set()))
    assert r.items[0].source_ids == ("e1",)


def test_used_sources_only_cited_and_in_source_order(sources):
    r = ok(
        validate(
            cand([("장보기를 했어요", ["t1"]), ("학교 공연이 있었어요", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [s.id for s in r.used_sources] == ["t1", "e1"]  # 근거 목록 순서(날짜순)
    assert all(isinstance(s, Source) for s in r.used_sources)


def test_dropped_sentence_sources_not_in_used(sources):
    r = ok(
        validate(
            cand([("문서 이야기 99", ["d1"]), ("학교 공연이 있었어요", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [s.id for s in r.used_sources] == ["e1"]


# ── validate: 숫자 ────────────────────────────────────────────


def test_number_not_in_sources_dropped(sources):
    r = ok(
        validate(
            cand([("학교 공연에 500명이 왔어요", ["e1"]), ("학교 공연이 있었어요", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [i.text for i in r.items] == ["학교 공연이 있었어요"]


def test_date_numbers_allowed(sources):
    r = ok(validate(cand([("11월 10일에 학교 공연이 있었어요", ["e1"])]), sources, set()))
    assert len(r.items) == 1
    r = ok(validate(cand([("2026년 11월 10일 학교 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_zero_padded_date_numbers_match_by_value(sources):
    r = ok(validate(cand([("11월 09일에 장보기", ["t1"])]), sources, set()))
    assert len(r.items) == 1
    r = ok(validate(cand([("11월 9일에 장보기", ["t1"])]), sources, set()))
    assert len(r.items) == 1


def test_time_numbers_allowed_24h_and_12h(sources):
    for text in ("14:30 학교 공연", "14시 30분 학교 공연", "오후 2시 30분 학교 공연"):
        r = ok(validate(cand([(text, ["e1"])]), sources, set()))
        assert len(r.items) == 1, text


def test_wrong_time_dropped(sources):
    r = validate(cand([("오후 3시에 학교 공연", ["e1"])]), sources, set())
    assert isinstance(r, Failed)


def test_midnight_and_noon_12h_forms():
    s = build_sources(
        [rec("event", "a", "야식", D10, "00:30"), rec("event", "b", "점심", D10, "12:00")]
    )
    r = ok(validate(cand([("오전 12시 30분 야식", ["e1"])]), s, set()))
    assert len(r.items) == 1
    r = ok(validate(cand([("낮 12시 점심", ["e2"])]), s, set()))
    assert len(r.items) == 1


def test_date_of_other_source_not_allowed(sources):
    # t1 은 11/09. 11월 10일(다른 근거의 날짜)을 t1 문장에 쓰면 안 된다
    r = validate(cand([("11월 10일에 장보기", ["t1"])]), sources, set())
    assert isinstance(r, Failed)


def test_number_from_other_sources_label_not_allowed(sources):
    # d1 라벨의 "11" 은 d1 인용 때만 허용, 숫자 "30"(e1 시각)은 d1 문장엔 불가
    r = validate(cand([("가정통신문 30건", ["d1"])]), sources, set())
    assert isinstance(r, Failed)


def test_number_in_label_allowed():
    s = build_sources([rec("event", "a", "3학년 학부모 상담", D10)])
    r = ok(validate(cand([("3학년 학부모 상담이 있었어요", ["e1"])]), s, set()))
    assert len(r.items) == 1


def test_default_counts_per_kind_and_total_allowed(sources):
    # 재료: 약속 2, 할 일 2, 문서 1, 전체 5
    for text, ids in (
        ("약속이 2건 있었어요", ["e1", "e2"]),
        ("할 일 2건", ["t1", "t2"]),
        ("문서 1건", ["d1"]),
        ("모두 5건의 기록", ["e1"]),
    ):
        r = ok(validate(cand([(text, ids)]), sources, set()))
        assert len(r.items) == 1, text


def test_count_not_matching_any_count_dropped(sources):
    for text in ("약속이 3건 있었어요", "약속이 4건 있었어요", "약속이 7건 있었어요"):
        r = validate(cand([(text, ["e1"])]), sources, set())
        assert isinstance(r, Failed), text


def test_explicit_counts_extend_allowed_numbers(sources):
    r = validate(cand([("완료율은 3건", ["e1"])]), sources, set())
    assert isinstance(r, Failed)
    r = ok(validate(cand([("완료율은 3건", ["e1"])]), sources, set(), counts={3}))
    assert len(r.items) == 1


def test_counts_accepts_any_collection(sources):
    r = ok(validate(cand([("총 8건", ["e1"])]), sources, set(), counts=[8]))
    assert len(r.items) == 1
    r = ok(validate(cand([("총 8건", ["e1"])]), sources, set(), counts=(8,)))
    assert len(r.items) == 1


def test_zero_count_allowed_when_a_kind_is_empty():
    s = build_sources([rec("event", "a", "공연", D10)])
    r = ok(validate(cand([("문서는 0건", ["e1"])]), s, set()))
    assert len(r.items) == 1


def test_digit_free_sentence_passes_number_rule(sources):
    r = ok(validate(cand([("가족이 함께 바빴어요", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_multiple_numbers_all_must_be_supported(sources):
    r = validate(cand([("11월 10일 14:30 에 777명", ["e1"])]), sources, set())
    assert isinstance(r, Failed)


def test_fullwidth_digits_are_checked_too(sources):
    r = validate(cand([("학교 공연 ５００명", ["e1"])]), sources, set())
    assert isinstance(r, Failed)
    r = ok(validate(cand([("１１월 １０일 학교 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_numbers_inside_ids_in_text_are_just_numbers(sources):
    # 문장에 id 가 그대로 박혀 있어도(e1) 숫자 1 은 건수 1 로 허용되는 정도다. 다른 숫자는 불가
    r = validate(cand([("e77 학교 공연", ["e1"])]), sources, set())
    assert isinstance(r, Failed)


# ── validate: 이름 ────────────────────────────────────────────


def test_member_name_not_in_cited_label_dropped(sources):
    r = validate(cand([("민수가 학교 공연에 갔어요", ["e1"])]), sources, {"민수", "지은"})
    assert isinstance(r, Failed)


def test_member_name_in_cited_label_allowed():
    s = build_sources([rec("event", "a", "민수 치과 예약", D10, "10:00")])
    r = ok(validate(cand([("민수의 치과 예약이 있었어요", ["e1"])]), s, {"민수", "지은"}))
    assert len(r.items) == 1


def test_member_name_in_other_sources_label_not_enough():
    s = build_sources(
        [rec("event", "a", "민수 치과 예약", D10, "10:00"), rec("event", "b", "학교 공연", D11)]
    )
    # 민수가 e1 라벨에 있어도 e2 만 인용한 문장은 안 된다
    r = validate(cand([("민수가 학교 공연에 갔어요", ["e2"])]), s, {"민수"})
    assert isinstance(r, Failed)
    r = ok(validate(cand([("민수가 학교 공연에 갔어요", ["e1", "e2"])]), s, {"민수"}))
    assert len(r.items) == 1


def test_name_check_ignored_when_no_member_names(sources):
    r = ok(validate(cand([("민수가 학교 공연에 갔어요", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_blank_member_names_are_ignored(sources):
    r = ok(validate(cand([("학교 공연이 있었어요", ["e1"])]), sources, {"", "  "}))
    assert len(r.items) == 1


def test_names_are_substring_matched():
    s = build_sources([rec("event", "a", "학교 공연", D10)])
    # 부분 문자열 포함: 이름이 다른 단어 안에 들어 있어도 걸린다(알려진 오탐)
    r = validate(cand([("하나로마트에 갔어요", ["e1"])]), s, {"하나"})
    assert isinstance(r, Failed)


def test_name_in_label_with_particle_still_matches():
    s = build_sources([rec("todo", "a", "지은 숙제 확인", D10)])
    r = ok(validate(cand([("지은이의 숙제를 확인했어요", ["t1"])]), s, {"지은"}))
    assert len(r.items) == 1


# ── validate: 길이·개수·중복·형태 ─────────────────────────────


def test_empty_and_blank_text_dropped(sources):
    r = ok(
        validate(
            cand([("", ["e1"]), ("   \n ", ["e1"]), ("학교 공연", ["e1"])]),
            sources,
            set(),
        )
    )
    assert [i.text for i in r.items] == ["학교 공연"]


def test_non_string_text_dropped(sources):
    c = {
        "title": "제목",
        "items": [
            {"text": None, "source_ids": ["e1"]},
            {"text": 5, "source_ids": ["e1"]},
            {"text": "학교 공연", "source_ids": ["e1"]},
        ],
    }
    assert [i.text for i in ok(validate(c, sources, set())).items] == ["학교 공연"]


def test_non_dict_item_dropped(sources):
    c = {
        "title": "제목",
        "items": ["그냥 문자열", None, 3, {"text": "학교 공연", "source_ids": ["e1"]}],
    }
    assert [i.text for i in ok(validate(c, sources, set())).items] == ["학교 공연"]


def test_max_text_boundary(sources):
    at_limit = "가" * MAX_TEXT
    over = "가" * (MAX_TEXT + 1)
    r = ok(validate(cand([(over, ["e1"]), (at_limit, ["e1"])]), sources, set()))
    assert [len(i.text) for i in r.items] == [MAX_TEXT]


def test_length_measured_after_whitespace_normalization(sources):
    padded = "  " + "가" * MAX_TEXT + "  \n"
    r = ok(validate(cand([(padded, ["e1"])]), sources, set()))
    assert r.items[0].text == "가" * MAX_TEXT


def test_inner_whitespace_collapsed(sources):
    r = ok(validate(cand([("학교   공연이\n있었어요", ["e1"])]), sources, set()))
    assert r.items[0].text == "학교 공연이 있었어요"


def test_duplicate_sentences_removed_first_wins(sources):
    r = ok(
        validate(
            cand([("학교 공연", ["e1"]), ("학교   공연", ["e1"]), ("학교 공연", ["e2"])]),
            sources,
            set(),
        )
    )
    assert len(r.items) == 1
    assert r.items[0].source_ids == ("e1",)


def test_duplicate_of_dropped_sentence_does_not_block_valid_copy(sources):
    # 첫 문장은 근거가 비어 버려지고, 같은 문장이 근거와 함께 다시 오면 살아남는다
    r = ok(validate(cand([("학교 공연", []), ("학교 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_max_items_truncates_to_first_six(sources):
    assert MAX_ITEMS == 6
    items = [(f"학교 공연 이야기 {'가' * k}", ["e1"]) for k in range(1, 10)]
    r = ok(validate(cand(items), sources, set()))
    assert len(r.items) == MAX_ITEMS
    assert [i.text for i in r.items] == [t for t, _ in items[:MAX_ITEMS]]


def test_exactly_max_items_kept(sources):
    items = [(f"학교 공연 {'가' * k}", ["e1"]) for k in range(1, MAX_ITEMS + 1)]
    assert len(ok(validate(cand(items), sources, set())).items) == MAX_ITEMS


def test_truncated_items_do_not_contribute_used_sources(sources):
    items = [(f"학교 공연 {'가' * k}", ["e1"]) for k in range(1, MAX_ITEMS + 1)]
    items.append(("장보기를 했어요", ["t1"]))  # 7번째 → 잘림
    r = ok(validate(cand(items), sources, set()))
    assert [s.id for s in r.used_sources] == ["e1"]


def test_dropped_invalid_sentences_do_not_use_up_slots(sources):
    items = [("근거 없음", [])] * 5 + [(f"학교 공연 {'가' * k}", ["e1"]) for k in range(1, 7)]
    assert len(ok(validate(cand(items), sources, set())).items) == 6


# ── validate: 제목 ────────────────────────────────────────────


def test_good_title_kept(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="공연 있는 한 주"), sources, set()))
    assert r.title == "공연 있는 한 주"


def test_title_whitespace_normalized(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="  공연   한 주 \n"), sources, set()))
    assert r.title == "공연 한 주"


def test_missing_or_blank_or_wrong_type_title_falls_back(sources):
    for title in (None, "", "   ", 5, ["a"]):
        c = cand([("학교 공연", ["e1"])])
        c["title"] = title
        assert ok(validate(c, sources, set())).title == FALLBACK_TITLE, title
    c = cand([("학교 공연", ["e1"])])
    del c["title"]
    assert ok(validate(c, sources, set())).title == FALLBACK_TITLE


def test_title_with_unsupported_number_falls_back(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="공연 500명 대성황"), sources, set()))
    assert r.title == FALLBACK_TITLE


def test_title_number_supported_by_used_source_kept(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="11월 10일 공연"), sources, set()))
    assert r.title == "11월 10일 공연"


def test_title_number_only_supported_by_unused_source_falls_back(sources):
    # 11월 9일 은 t1 날짜인데 문장은 e1 만 인용했다 → 제목은 쓸 수 없다
    r = ok(validate(cand([("학교 공연", ["e1"])], title="11월 9일 한 주"), sources, set()))
    assert r.title == FALLBACK_TITLE


def test_title_with_unsupported_name_falls_back(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="민수의 한 주"), sources, {"민수"}))
    assert r.title == FALLBACK_TITLE


def test_title_with_name_in_used_label_kept():
    s = build_sources([rec("event", "a", "민수 치과 예약", D10, "10:00")])
    r = ok(validate(cand([("민수의 치과 예약", ["e1"])], title="민수의 한 주"), s, {"민수"}))
    assert r.title == "민수의 한 주"


def test_title_too_long_falls_back(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="가" * (MAX_TEXT + 1)), sources, set()))
    assert r.title == FALLBACK_TITLE


def test_title_counts_allowed_numbers(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="약속 2건"), sources, set()))
    assert r.title == "약속 2건"


def test_fallback_title_value():
    assert FALLBACK_TITLE == "이번 주 우리 가족"


# ── validate: 실패 ────────────────────────────────────────────


def test_zero_remaining_sentences_is_failed(sources):
    r = validate(cand([("근거 없음", []), ("없는 id", ["zz"])]), sources, set())
    assert isinstance(r, Failed)
    assert r.reason == "no_valid_items"


def test_empty_items_is_failed(sources):
    r = validate({"title": "제목", "items": []}, sources, set())
    assert isinstance(r, Failed)
    assert r.reason == "no_items"


def test_bad_shapes_are_failed_not_exceptions(sources):
    for c in (
        None,
        [],
        "text",
        3,
        {},
        {"title": "x"},
        {"title": "x", "items": "문자열"},
        {"title": "x", "items": None},
    ):
        r = validate(c, sources, set())
        assert isinstance(r, Failed), c
        assert r.reason in {"bad_shape", "no_items"}


def test_empty_sources_means_everything_fails():
    r = validate(cand([("무언가", ["e1"])]), [], set())
    assert isinstance(r, Failed)


def test_failed_reason_never_contains_input_text(sources):
    secret = "비밀문장홍길동의계좌1234"
    r = validate(cand([(secret, []), (secret + "2", ["zz"])]), sources, {"홍길동"})
    assert isinstance(r, Failed)
    assert secret not in r.reason
    assert "홍길동" not in r.reason
    assert "1234" not in r.reason
    assert r.reason.isidentifier()  # 짧은 고정 코드 문자열


def test_failed_reason_is_from_fixed_set(sources):
    reasons = set()
    for c in (
        None,
        {"title": "x", "items": []},
        cand([("a", [])]),
        cand([("민수", ["e1"])]),
    ):
        r = validate(c, sources, {"민수"})
        assert isinstance(r, Failed)
        reasons.add(r.reason)
    assert reasons <= {"bad_shape", "no_items", "no_valid_items"}


def test_failed_has_only_reason_field():
    assert [f.name for f in dataclasses.fields(Failed)] == ["reason"]


def test_validate_does_not_mutate_inputs(sources):
    c = cand([("학교 공연", ["e1", "e1"]), ("근거 없음", [])])
    before = repr(c)
    src_before = list(sources)
    validate(c, sources, {"민수"})
    assert repr(c) == before
    assert sources == src_before


def test_validated_is_immutable(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])]), sources, set()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.title = "x"


# ── 리뷰 반영: 유니코드 우회 ──────────────────────────────────

INVISIBLES = [
    "​",  # ZWSP
    "‌",  # ZWNJ
    "‍",  # ZWJ
    "⁠",  # word joiner
    "﻿",  # BOM
    "­",  # soft hyphen
    "‮",  # 방향 제어
    "ㅤ",  # 한글 채움 문자(Lo 이지만 보이지 않음)
]


def test_nfd_sentence_name_still_blocked(sources):
    text = unicodedata.normalize("NFD", "민수가 학교 공연에 갔어요")
    assert text != unicodedata.normalize("NFC", text)
    r = validate(cand([(text, ["e1"])]), sources, {"민수"})
    assert isinstance(r, Failed)


def test_nfd_member_name_still_blocks_nfc_sentence(sources):
    name = unicodedata.normalize("NFD", "민수")
    r = validate(cand([("민수가 학교 공연에 갔어요", ["e1"])]), sources, {name})
    assert isinstance(r, Failed)


def test_nfd_label_matches_nfc_name_and_sentence():
    label = unicodedata.normalize("NFD", "민수 치과 예약")
    s = build_sources([rec("event", "a", label, D10)])
    r = ok(validate(cand([("민수의 치과 예약이 있었어요", ["e1"])]), s, {"민수"}))
    assert len(r.items) == 1


def test_source_not_built_by_build_sources_is_still_compared_normalized():
    # build_sources 를 거치지 않고 만든 Source 라도 비교는 정규화해서 한다
    raw = Source(
        id="e1",
        kind="event",
        ref="a",
        label=unicodedata.normalize("NFD", "민수 치과"),
        date=D10,
        time=None,
    )
    r = ok(validate(cand([("민수 치과 예약", ["e1"])]), [raw], {"민수"}))
    assert len(r.items) == 1


@pytest.mark.parametrize("ch", INVISIBLES)
def test_invisible_char_inside_name_still_blocked(sources, ch):
    r = validate(cand([(f"민{ch}수가 학교 공연에 갔어요", ["e1"])]), sources, {"민수"})
    assert isinstance(r, Failed)


@pytest.mark.parametrize("ch", INVISIBLES)
def test_invisible_char_inside_member_name_still_blocked(sources, ch):
    r = validate(cand([("민수가 학교 공연에 갔어요", ["e1"])]), sources, {f"민{ch}수"})
    assert isinstance(r, Failed)


def test_many_mixed_invisibles_inside_name_blocked(sources):
    r = validate(cand([("민​‍﻿수가 학교 공연", ["e1"])]), sources, {"민수"})
    assert isinstance(r, Failed)


def test_invisible_char_in_label_does_not_hide_name_match():
    s = build_sources([rec("event", "a", "민​수 치과", D10)])
    assert s[0].label == "민수 치과"
    r = ok(validate(cand([("민수 치과 예약", ["e1"])]), s, {"민수"}))
    assert len(r.items) == 1


def test_stored_text_is_the_normalized_text_that_was_checked(sources):
    raw = unicodedata.normalize("NFD", "학교​ 공연﻿이 있었어요")
    r = ok(validate(cand([(raw, ["e1"])]), sources, {"민수"}))
    text = r.items[0].text
    assert text == "학교 공연이 있었어요"
    assert text == unicodedata.normalize("NFKC", text)
    assert not any(unicodedata.category(c) == "Cf" for c in text)


def test_stored_title_is_normalized(sources):
    title = unicodedata.normalize("NFD", "공연​ 있는 한 주")
    r = ok(validate(cand([("학교 공연", ["e1"])], title=title), sources, set()))
    assert r.title == "공연 있는 한 주"


def test_title_name_with_zwsp_falls_back(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="민​수의 한 주"), sources, {"민수"}))
    assert r.title == FALLBACK_TITLE


def test_text_only_invisibles_is_empty_and_dropped(sources):
    r = validate(cand([("​‍ ﻿", ["e1"])]), sources, set())
    assert isinstance(r, Failed)


def test_duplicates_detected_after_invisible_removal(sources):
    r = ok(validate(cand([("학교 공연", ["e1"]), ("학교​ 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_name_match_is_case_insensitive(sources):
    r = validate(cand([("MINSU 가 학교 공연에 갔어요", ["e1"])]), sources, {"Minsu"})
    assert isinstance(r, Failed)


def test_label_with_invisible_char_is_cleaned_by_build():
    s = build_sources([rec("event", "a", "치과​ 예약﻿", D10)])
    assert s[0].label == "치과 예약"


# ── 리뷰 반영: ASCII 가 아닌 숫자 ─────────────────────────────


@pytest.mark.parametrize(
    "digits",
    [
        "٣٣",  # 아랍-인도
        "۳۳",  # 확장 아랍-인도
        "३३",  # 데바나가리
        "৩৩",  # 벵골
        "３３",  # 전각
        "٣3",  # 섞어 쓴 토큰
    ],
)
def test_non_ascii_digits_unsupported_number_dropped(sources, digits):
    r = validate(cand([(f"{digits}명이 학교 공연에 왔어요", ["e1"])]), sources, set())
    assert isinstance(r, Failed)


def test_non_ascii_digits_compared_by_value(sources):
    # 11월 10일 을 아랍-인도 숫자로 쓰면 값이 같아서 허용
    r = ok(validate(cand([("١١월 ١٠일 학교 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1
    # 앞자리 0 도 값으로 비교(11월 09일 = t1)
    r = ok(validate(cand([("११월 ०९일에 장보기", ["t1"])]), sources, set()))
    assert len(r.items) == 1


def test_non_ascii_digit_in_title_unsupported_falls_back(sources):
    r = ok(validate(cand([("학교 공연", ["e1"])], title="٣٣명 대성황"), sources, set()))
    assert r.title == FALLBACK_TITLE


def test_huge_digit_run_does_not_crash():
    s = build_sources([rec("event", "a", "가" + "1" * 6000, D10)])
    assert isinstance(validate(cand([("가", ["e1"])]), s, set()), Validated)
    assert isinstance(validate(cand([("2" * 100, ["e1"])]), s, set()), Failed)


# ── 리뷰 반영: 입력 방어 ──────────────────────────────────────


def test_invalid_counts_values_are_ignored_not_raised(sources):
    r = validate(cand([("완료 3건", ["e1"])]), sources, set(), counts=["x", None, 3.5, True, {}])
    assert isinstance(r, Failed)  # 3.5 가 3 으로 새어 들어가면 안 된다
    r = ok(validate(cand([("완료 3건", ["e1"])]), sources, set(), counts=["x", None, 3]))
    assert len(r.items) == 1  # 나머지 값이 잘못돼도 올바른 값은 쓴다


def test_candidate_items_processed_up_to_cap(sources):
    # 후보는 앞 50개까지만 본다(처리량 상한). 51번째 이후의 정상 문장은 쓰지 않는다
    bad = [("근거 없음", [])] * 50
    assert isinstance(validate(cand(bad + [("학교 공연", ["e1"])]), sources, set()), Failed)
    r = ok(validate(cand(bad[:49] + [("학교 공연", ["e1"])]), sources, set()))
    assert len(r.items) == 1


def test_huge_candidate_list_is_bounded(sources):
    items = [("근거 없음", [])] * 100_000
    assert isinstance(validate(cand(items), sources, set()), Failed)


# ── 한계를 시험으로 고정(evidence.py docstring 의 "한계" 와 짝) ──


def test_known_limit_small_numbers_overlap_counts_and_hours(sources):
    # 건수(2)·12시간제 시(14:30 → 2)·월(11) 과 겹치는 작은 숫자는 단위가 달라도 통과한다.
    # 단위 접미사("명"·"월"·"건")까지 구분하는 보강은 T26-b 과제다. 이 시험이 바뀌면 문서도 같이 고친다.
    for text in ("학교 공연에 2명이 왔어요", "학교 공연에 11명이 왔어요"):
        r = ok(validate(cand([(text, ["e1"])]), sources, set()))
        assert len(r.items) == 1, text
    # 겹치지 않는 숫자는 막힌다
    r = validate(cand([("학교 공연에 33명이 왔어요", ["e1"])]), sources, set())
    assert isinstance(r, Failed)
