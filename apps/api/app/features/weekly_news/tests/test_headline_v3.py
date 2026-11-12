"""헤드라인 v3: 짧은 헤드라인(20자), 요일 검증, 프롬프트에 요일 제공. 외부 의존 없는 순수 함수만 다룬다.

헤드라인·본문·제목에 쓴 요일은 인용한 근거 날짜의 요일이어야 한다(모델이 엉뚱한 요일을 쓰지 못하게 서버가 대조한다).
"""

from datetime import date

import pytest

from app.features.weekly_news import generate
from app.features.weekly_news.evidence import (
    FALLBACK_TITLE,
    MAX_HEADLINE,
    Failed,
    SourceRecord,
    Validated,
    build_sources,
    validate,
)

D09, D10, D11 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)  # 월 화 수


def rec(kind, ref, title, day, start_time=None):
    return SourceRecord(kind=kind, ref=ref, title=title, day=day, start_time=start_time)


@pytest.fixture
def sources():
    return build_sources(
        [
            rec("event", "a", "학교 공연", D10, "14:30"),  # 화요일
            rec("event", "b", "가족 저녁 식사", D11),  # 수요일
            rec("todo", "c", "장보기", D09),  # 월요일
        ]
    )


def sid(sources, label):
    return next(s.id for s in sources if s.label == label)


def run(sources, items, title="공연이 있던 주"):
    return validate({"title": title, "items": items}, sources, [], article_mode=True)


def art(text, ids, headline=None):
    item = {"text": text, "source_ids": ids}
    if headline is not None:
        item["headline"] = headline
    return item


def ok(result):
    assert isinstance(result, Validated), result
    return result


# ── 헤드라인은 짧게 ───────────────────────────────────────────


def test_headline_limit_is_twenty_characters(sources):
    assert MAX_HEADLINE == 20
    show = sid(sources, "학교 공연")
    twenty, twenty_one = "가" * 20, "가" * 21
    assert (
        ok(run(sources, [art("학교 공연이 있었어요", [show], twenty)])).items[0].headline == twenty
    )
    assert (
        ok(run(sources, [art("학교 공연이 있었어요", [show], twenty_one)])).items[0].headline
        is None
    )


# ── 요일 검증 ─────────────────────────────────────────────────


def test_weekday_in_text_must_match_the_cited_date(sources):
    show = sid(sources, "학교 공연")  # 2026-11-10 = 화요일
    assert len(ok(run(sources, [art("화요일에 학교 공연이 있었어요", [show])])).items) == 1
    assert isinstance(run(sources, [art("수요일에 학교 공연이 있었어요", [show])]), Failed)


def test_weekday_in_headline_must_match_or_the_headline_is_dropped(sources):
    show = sid(sources, "학교 공연")
    good = ok(run(sources, [art("학교 공연이 있었어요", [show], "화요일, 학교 공연 일정")]))
    assert good.items[0].headline == "화요일, 학교 공연 일정"
    bad = ok(run(sources, [art("학교 공연이 있었어요", [show], "금요일, 학교 공연 일정")]))
    assert bad.items[0].headline is None and bad.items[0].text == "학교 공연이 있었어요"


def test_an_article_grouping_different_days_may_not_use_weekday_words(sources):
    """요일을 일정별로 연결해 검증할 수 없으므로(요일을 뒤바꿔도 집합은 같다) 날짜가 다른 기록을 묶은 기사는 요일을 쓰지 않는다."""
    show, dinner = (
        sid(sources, "학교 공연"),
        sid(sources, "가족 저녁 식사"),
    )  # 화·수, 같은 종류(event)
    for text in (
        "화요일 학교 공연과 수요일 가족 저녁 식사 일정이 있었어요",
        "수요일 학교 공연과 화요일 가족 저녁 식사 일정이 있었어요",  # 뒤바꿈
    ):
        assert isinstance(run(sources, [art(text, [show, dinner])]), Failed), text
    plain = "학교 공연과 가족 저녁 식사 일정이 있었어요"
    res = ok(run(sources, [art(plain, [show, dinner], "화요일, 학교 공연 일정")]))
    assert len(res.items) == 1 and res.items[0].headline is None  # 헤드라인의 요일도 마찬가지


def test_a_grouped_article_on_the_same_day_may_use_that_weekday():
    srcs = build_sources(
        [rec("event", "a", "학교 공연", D10), rec("event", "b", "가족 저녁 식사", D10)]
    )
    text = "화요일에 학교 공연과 가족 저녁 식사 일정이 있었어요"
    assert len(ok(run(srcs, [art(text, [srcs[0].id, srcs[1].id])])).items) == 1


def test_a_weekday_word_inside_a_quoted_title_is_not_a_claim():
    srcs = build_sources(
        [rec("event", "a", "금요일의 약속", D10)]
    )  # 화요일 일정의 제목이 금요일의 약속
    assert len(ok(run(srcs, [art("금요일의 약속 일정이 있었어요", [srcs[0].id])])).items) == 1
    assert isinstance(run(srcs, [art("금요일에 약속 일정이 있었어요", [srcs[0].id])]), Failed)


@pytest.mark.parametrize("variant", ["금 요일", "금요 일", "금욜", "금 욜"])
def test_spacing_and_short_forms_do_not_hide_a_weekday(sources, variant):
    show = sid(sources, "학교 공연")
    text = f"{variant} 학교 공연 일정이 있었어요"
    if variant == "금요 일":
        # '요 일' 처럼 요와 일 사이를 띄운 것은 요일 낱말이 아니라 일반 글이다(검증 대상 아님)
        assert len(ok(run(sources, [art(text, [show])])).items) == 1
    else:
        assert isinstance(run(sources, [art(text, [show])]), Failed), variant
        bad = ok(run(sources, [art("학교 공연 일정이 있었어요", [show], f"{variant}, 학교 공연")]))
        assert bad.items[0].headline is None


def test_pseudonym_token_counts_short_in_the_first_check_and_real_length_in_the_second():
    """복원 전에는 이름이 2자로 복원되는 경우까지 살리려고 토큰을 2자로 센다(복원 뒤 검증이 실제 길이로 다시 본다)."""
    srcs = build_sources([rec("event", "a", "[PERSON_1] 학교 공연", D10)])
    twenty = "[PERSON_1]" + "가" * 18  # 이름이 2자로 복원되면 20자
    twenty_one = "[PERSON_1]" + "가" * 19
    assert (
        ok(run(srcs, [art("[PERSON_1] 학교 공연이 있었어요", [srcs[0].id], twenty)]))
        .items[0]
        .headline
        == twenty
    )
    assert (
        ok(run(srcs, [art("[PERSON_1] 학교 공연이 있었어요", [srcs[0].id], twenty_one)]))
        .items[0]
        .headline
        is None
    )


@pytest.mark.parametrize(
    "phrase",
    ["월·화요일에", "월, 화요일에", "월~화요일에", "11월 10일(수)에", "11월 10일 (수) 에"],
)
def test_weekday_lists_and_parenthesized_weekdays_are_checked(sources, phrase):
    """범위·나열("월·화요일")은 모든 글자를, 날짜 표기 "11월 10일(수)" 의 괄호 요일도 근거와 대조한다."""
    show = sid(sources, "학교 공연")  # 화요일
    assert isinstance(run(sources, [art(f"{phrase} 학교 공연 일정이 있었어요", [show])]), Failed), (
        phrase
    )


def test_the_correct_weekday_in_a_parenthesized_date_is_fine(sources):
    show = sid(sources, "학교 공연")
    assert (
        len(ok(run(sources, [art("11월 10일(화)에 학교 공연 일정이 있었어요", [show])])).items) == 1
    )


def test_prompt_matches_what_the_server_requires_of_event_text():
    from app.features.weekly_news.evidence import SCHEDULE_WORDS

    for phrase in ("있었어요", "잡혀 있었어요"):
        assert phrase in generate.SYSTEM
    assert "시간대" in generate.SYSTEM  # 시각이 없으면 저녁·오후 같은 시간대 표현을 지어내지 않는다
    assert "있었" in SCHEDULE_WORDS


def test_each_weekday_word_is_checked_not_only_the_first(sources):
    show = sid(sources, "학교 공연")
    assert isinstance(run(sources, [art("화요일과 목요일에 학교 공연이 있었어요", [show])]), Failed)


def test_top_level_title_weekday_is_checked_too(sources):
    show = sid(sources, "학교 공연")
    res = ok(run(sources, [art("학교 공연이 있었어요", [show])], title="목요일 공연 소식"))
    assert res.title == FALLBACK_TITLE


def test_words_that_merely_contain_a_weekday_letter_are_not_weekdays(sources):
    show = sid(sources, "학교 공연")
    # '요일' 이 붙지 않은 글자(화·수·토 …)는 요일이 아니다
    assert len(ok(run(sources, [art("학교 공연 화면 소식이 있었어요", [show])])).items) == 1


# ── 프롬프트: 요일을 서버가 계산해 준다 ────────────────────────


def test_prompt_rows_carry_a_server_computed_weekday(sources):
    import json

    text = generate._prompt(sources, date(2026, 11, 9))
    rows = json.loads(text.split("기록:\n")[1])
    by_title = {r["title"]: r for r in rows}
    assert by_title["학교 공연"]["weekday"] == "화요일"
    assert by_title["가족 저녁 식사"]["weekday"] == "수요일"
    assert by_title["장보기"]["weekday"] == "월요일"
    assert set(rows[0]) == {
        "id",
        "kind",
        "date",
        "weekday",
        "time",
        "title",
    }  # 새로 나가는 개인정보는 없다


def test_prompt_version_and_guidance_for_short_headlines():
    assert generate.PROMPT_VERSION == "v3"
    for phrase in ("20자", "요일", "명사구", "던 주", "같은 말"):
        assert phrase in generate.SYSTEM, phrase
