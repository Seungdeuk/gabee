"""기사형 뉴스(헤드라인·메인·단신) 검증 시험. 외부 의존 없는 순수 함수만 다룬다.

규칙: 메인 기사는 근거 수가 많은 것(같으면 이른 날짜, 그래도 같으면 후보 순서)으로 정한다. 묶은 기사는 같은 날짜이거나 같은 종류의 근거만
묶을 수 있고, 사건 사이의 관계·원인·결과를 말하면 버린다. 약속(event)을 인용한 문장은 참석·완료·방문한 것처럼 쓰면 버린다.
"""

from datetime import date

import pytest

from app.features.weekly_news.evidence import (
    MAX_ARTICLES,
    Failed,
    SourceRecord,
    Validated,
    build_sources,
    validate,
)

D09, D10, D11 = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)


def rec(kind, ref, title, day, start_time=None):
    return SourceRecord(kind=kind, ref=ref, title=title, day=day, start_time=start_time)


RECORDS = [
    rec("event", "ev-1", "학교 공연", D10, "14:30"),
    rec("event", "ev-2", "가족 저녁 식사", D10, "18:00"),
    rec("event", "ev-3", "할머니 댁 방문", D11),
    rec("todo", "td-1", "장보기", D09),
    rec("todo", "td-2", "분리수거", D11),
    rec("document", "doc-1", "가정통신문", D10),
]


@pytest.fixture
def sources():
    return build_sources(RECORDS)


def sid(sources, label):
    return next(s.id for s in sources if s.label == label)


def art(text, ids, headline=None):
    item = {"text": text, "source_ids": ids}
    if headline is not None:
        item["headline"] = headline
    return item


def run(sources, items, title="이번 주 정리"):
    return validate({"title": title, "items": items}, sources, [], article_mode=True)


def ok(result):
    assert isinstance(result, Validated), result
    return result


# ── 메인 기사 선정(결정적) ────────────────────────────────────


def test_lead_is_the_article_with_the_most_sources(sources):
    show, dinner, td = (
        sid(sources, "학교 공연"),
        sid(sources, "가족 저녁 식사"),
        sid(sources, "장보기"),
    )
    res = ok(
        run(
            sources,
            [
                art("장보기가 있었어요", [td]),
                art("학교 공연과 가족 저녁 식사가 있었어요", [show, dinner]),
            ],
        )
    )
    assert [i.role for i in res.items] == ["lead", "brief"]
    assert res.items[0].source_ids == (show, dinner)


def test_tie_goes_to_the_earliest_date_then_candidate_order(sources):
    visit, show, td = (
        sid(sources, "할머니 댁 방문"),
        sid(sources, "학교 공연"),
        sid(sources, "장보기"),
    )
    res = ok(
        run(
            sources,
            [
                art("할머니 댁 방문 일정이 있었어요", [visit]),  # 11/11
                art("학교 공연이 있었어요", [show]),  # 11/10
                art("장보기가 있었어요", [td]),  # 11/9
            ],
        )
    )
    assert res.items[0].source_ids == (td,)  # 근거 수가 같으면 가장 이른 날짜가 메인
    assert [i.role for i in res.items] == ["lead", "brief", "brief"]
    # 단신은 이른 날짜 순
    assert [i.source_ids[0] for i in res.items[1:]] == [show, visit]


def test_same_date_and_same_count_keeps_candidate_order(sources):
    show, dinner = sid(sources, "학교 공연"), sid(sources, "가족 저녁 식사")
    res = ok(
        run(
            sources,
            [art("가족 저녁 식사가 있었어요", [dinner]), art("학교 공연이 있었어요", [show])],
        )
    )
    assert res.items[0].source_ids == (dinner,)


def test_single_article_is_lead_only(sources):
    res = ok(run(sources, [art("장보기가 있었어요", [sid(sources, "장보기")])]))
    assert [i.role for i in res.items] == ["lead"]


# ── 분류(category): 인용 근거의 종류에서 서버가 정한다 ─────────


def test_category_comes_from_cited_kinds(sources):
    show, dinner = sid(sources, "학교 공연"), sid(sources, "가족 저녁 식사")
    td, doc = sid(sources, "분리수거"), sid(sources, "가정통신문")
    res = ok(
        run(
            sources,
            [
                art("학교 공연과 가족 저녁 식사가 있었어요", [show, dinner]),
                art("분리수거를 마쳤어요", [td]),
                art("가정통신문이 올라왔어요", [doc]),
                art(
                    "학교 공연과 가정통신문이 있었어요", [show, doc]
                ),  # 같은 날(11/10), 종류가 섞임
            ],
        )
    )
    cat = {i.source_ids: i.category for i in res.items}
    assert cat[(show, dinner)] == "일정"
    assert cat[(td,)] == "할 일"
    assert cat[(doc,)] == "문서"
    assert cat[(show, doc)] == "가족 소식"  # 종류가 섞이면 고정 이름


def test_model_supplied_category_or_role_is_ignored(sources):
    item = art("장보기가 있었어요", [sid(sources, "장보기")])
    item.update({"category": "교육", "role": "brief"})
    res = ok(run(sources, [item]))
    assert res.items[0].category == "할 일" and res.items[0].role == "lead"


# ── 묶기: 같은 날짜 또는 같은 종류만, 관계를 지어내지 않는다 ───


def test_grouping_needs_same_date_or_same_kind(sources):
    show, visit = (
        sid(sources, "학교 공연"),
        sid(sources, "할머니 댁 방문"),
    )  # 다른 날, 같은 종류(event)
    td, doc = sid(sources, "장보기"), sid(sources, "가정통신문")  # 다른 날(11/9, 11/10), 다른 종류
    res = run(
        sources,
        [
            art("학교 공연과 할머니 댁 방문 일정이 있었어요", [show, visit]),
            art("장보기와 가정통신문이 있었어요", [td, doc]),
        ],
    )
    kept = ok(res).items
    assert [i.source_ids for i in kept] == [(show, visit)]  # 날짜도 종류도 다른 묶음만 버린다


@pytest.mark.parametrize(
    "text",
    [
        "학교 공연이 있었고 그 덕분에 가족 저녁 식사가 있었어요",
        "학교 공연 때문에 가족 저녁 식사가 있었어요",
        "학교 공연이 있었어요. 그래서 가족 저녁 식사가 있었어요",
        "학교 공연 이후에 가족 저녁 식사가 있었어요",
        "학교 공연 뒤에 가족 저녁 식사가 있었어요",
        "학교 공연을 위해 가족 저녁 식사가 있었어요",
        "학교 공연의 결과로 가족 저녁 식사가 있었어요",
        "학교 공연에 이어 가족 저녁 식사가 있었어요",
        "학교 공연이 계기가 되어 가족 저녁 식사가 있었어요",
    ],
)
def test_grouped_article_may_not_state_relations(sources, text):
    show, dinner = sid(sources, "학교 공연"), sid(sources, "가족 저녁 식사")
    assert isinstance(run(sources, [art(text, [show, dinner])]), Failed)


def test_plain_grouping_without_relation_is_kept(sources):
    show, dinner = sid(sources, "학교 공연"), sid(sources, "가족 저녁 식사")
    res = ok(
        run(sources, [art("화요일에 학교 공연과 가족 저녁 식사 일정이 있었어요", [show, dinner])])
    )
    assert len(res.items) == 1


def test_every_cited_source_must_exist(sources):
    show = sid(sources, "학교 공연")
    assert isinstance(run(sources, [art("학교 공연이 있었어요", [show, "e99"])]), Failed)


def test_numbers_must_be_supported_by_all_cited_sources(sources):
    show, dinner = sid(sources, "학교 공연"), sid(sources, "가족 저녁 식사")
    res = run(sources, [art("11월 10일에 학교 공연과 가족 저녁 식사가 있었어요", [show, dinner])])
    assert len(ok(res).items) == 1
    assert isinstance(
        run(sources, [art("11월 12일에 학교 공연과 가족 저녁 식사가 있었어요", [show, dinner])]),
        Failed,
    )


# ── 약속은 진행·참석·방문한 것처럼 쓰지 않는다 ────────────────


@pytest.mark.parametrize(
    "text",
    [
        "학교 공연을 다녀왔어요",
        "학교 공연에 참석했어요",
        "학교 공연에 참가했어요",
        "학교 공연에 참여했어요",
        "학교 공연을 보러 갔어요",
        "학교 공연을 마쳤어요",
        "학교 공연이 무사히 끝났어요",
        "학교 공연이 잘 진행되었어요",
        "학교 공연이 잘 진행됐어요",
        "학교 공연이 열렸어요",
        "학교 공연을 치렀어요",
        "학교 공연에서 가족이 만났어요",
        "가족이 학교 공연을 함께했어요",
        "학교 공연에서 즐거운 시간을 보냈어요",
        "학교 공연을 즐겼어요",
        "학교 공연이 성공적으로 마무리됐어요",
        "학교 공연을 관람했어요",
        "학교 공연이 완료되었어요",
        "학교 공연에 들렀어요",
        "학교 공연을 다녀온 한 주였어요",
    ],
)
def test_event_articles_never_claim_the_activity_happened(sources, text):
    assert isinstance(run(sources, [art(text, [sid(sources, "학교 공연")])]), Failed)


@pytest.mark.parametrize(
    "text",
    [
        "화요일 오후 2시 30분에 학교 공연이 있었어요",
        "학교 공연이 잡혀 있었어요",
        "학교 공연이 예정되어 있었어요",
        "학교 공연 일정이 공유되어 있었어요",
        "학교 공연 일정이 등록되어 있었어요",
    ],
)
def test_event_articles_may_state_the_schedule_as_a_schedule(sources, text):
    assert len(ok(run(sources, [art(text, [sid(sources, "학교 공연")])])).items) == 1


def test_a_completed_todo_may_be_called_done(sources):
    assert (
        len(ok(run(sources, [art("분리수거를 마쳤어요", [sid(sources, "분리수거")])])).items) == 1
    )


def test_completion_wording_is_blocked_when_an_event_is_mixed_in(sources):
    td, visit = (
        sid(sources, "분리수거"),
        sid(sources, "할머니 댁 방문"),
    )  # 같은 날(11/11)이라 묶기는 허용된다
    assert isinstance(
        run(sources, [art("분리수거와 할머니 댁 방문 일정을 마쳤어요", [td, visit])]), Failed
    )


def test_a_title_may_be_quoted_even_if_it_contains_an_activity_word(sources):
    visit = sid(sources, "할머니 댁 방문")
    res = ok(run(sources, [art("할머니 댁 방문 일정이 있었어요", [visit])]))
    assert len(res.items) == 1
    assert isinstance(run(sources, [art("할머니 댁을 방문했어요", [visit])]), Failed)


# ── 헤드라인 ─────────────────────────────────────────────────


def test_valid_headline_is_kept_and_checked_like_the_text(sources):
    show = sid(sources, "학교 공연")
    res = ok(run(sources, [art("학교 공연이 있었어요", [show], headline="학교 공연 소식")]))
    assert res.items[0].headline == "학교 공연 소식"


@pytest.mark.parametrize(
    "headline",
    [
        "11월 12일 학교 공연",  # 근거에 없는 날짜
        "학교 공연을 다녀왔어요",  # 약속을 한 것처럼
        "학교 공연 덕분에 웃은 주",  # 관계(여러 근거가 아니어도 헤드라인은 관계를 말하지 않는다)
        "가" * 31,  # 너무 길다
        "",
    ],
)
def test_bad_headline_is_dropped_but_the_article_stays(sources, headline):
    show = sid(sources, "학교 공연")
    res = ok(run(sources, [art("학교 공연이 있었어요", [show], headline=headline)]))
    assert res.items[0].headline is None and res.items[0].text == "학교 공연이 있었어요"


def test_missing_headline_is_allowed_for_old_style_output(sources):
    res = ok(run(sources, [art("학교 공연이 있었어요", [sid(sources, "학교 공연")])]))
    assert res.items[0].headline is None


# ── 기사 수는 재료 수에 맞춘다 ────────────────────────────────


def test_article_count_never_exceeds_sources_or_the_cap():
    few = build_sources(
        [rec("event", "a", "학교 공연", D10), rec("event", "b", "가족 저녁 식사", D11)]
    )
    phrases = [
        "학교 공연이 있었어요",
        "학교 공연이 잡혀 있었어요",
        "학교 공연이 예정되어 있었어요",
        "학교 공연 일정이 공유되어 있었어요",
        "학교 공연 일정이 등록되어 있었어요",
    ]
    # 같은 근거만 인용한 기사는 되풀이하지 않는다(하나만 남는다)
    assert len(ok(run(few, [art(p, [few[0].id]) for p in phrases])).items) == 1
    distinct = phrases[:1] + ["가족 저녁 식사가 있었어요"]
    ids = [few[0].id, few[1].id]
    assert len(ok(run(few, [art(p, [i]) for p, i in zip(distinct, ids, strict=True)])).items) == 2
    many = build_sources(RECORDS)
    labels = ["학교 공연", "가족 저녁 식사", "할머니 댁 방문", "장보기", "분리수거", "가정통신문"]
    items = [art(f"{label}이 있었어요", [sid(many, label)]) for label in labels]
    assert len(ok(run(many, items)).items) == MAX_ARTICLES == 5


def test_two_sources_allow_at_most_two_articles():
    two = build_sources(
        [rec("event", "a", "학교 공연", D10), rec("event", "b", "가족 저녁 식사", D11)]
    )
    items = [
        art("학교 공연이 있었어요", [two[0].id]),
        art("가족 저녁 식사가 있었어요", [two[1].id]),
        art("학교 공연 일정이 등록되어 있었어요", [two[0].id]),
    ]
    assert len(ok(run(two, items)).items) == 2


def test_used_sources_follow_the_kept_articles_only(sources):
    show, td = sid(sources, "학교 공연"), sid(sources, "장보기")
    res = ok(run(sources, [art("학교 공연을 다녀왔어요", [show]), art("장보기가 있었어요", [td])]))
    assert [s.id for s in res.used_sources] == [td]


# ── Codex 독립 리뷰 반영(2026-11-12) ──────────────────────────


def test_a_quoted_title_cannot_hide_an_activity_claim_attached_to_it(sources):
    """제목 '할머니 댁 방문' 에 서술어를 붙여 '방문했어요' 라고 쓰면 제목 인용이 아니라 방문했다는 주장이다."""
    visit = sid(sources, "할머니 댁 방문")
    for text in ("할머니 댁 방문했어요", "할머니 댁 방문을 했어요", "할머니 댁 방문하였어요"):
        assert isinstance(run(sources, [art(text, [visit])]), Failed), text
    res = ok(
        run(sources, [art("할머니 댁 방문이 있었어요", [visit], headline="할머니 댁 방문 소식")])
    )
    assert res.items[0].headline == "할머니 댁 방문 소식"


@pytest.mark.parametrize(
    "text",
    [
        "청소에 힘입어 장보기를 마쳤어요",
        "청소의 영향으로 장보기를 마쳤어요",
        "청소를 비롯해 장보기를 마쳤어요",
        "청소에 앞서 장보기를 마쳤어요",
        "청소에 뒤이어 장보기를 마쳤어요",
        "청소가 잇따라 장보기를 마쳤어요",
    ],
)
def test_more_ways_of_stating_a_relation_are_blocked(text):
    srcs = build_sources([rec("todo", "a", "청소", D10), rec("todo", "b", "장보기", D10)])
    assert isinstance(run(srcs, [art(text, [srcs[0].id, srcs[1].id])]), Failed)
    res = ok(
        run(
            srcs,
            [
                art(
                    "청소와 장보기를 마쳤어요",
                    [srcs[0].id, srcs[1].id],
                    headline="청소에 힘입은 장보기",
                )
            ],
        )
    )
    assert res.items[0].headline is None  # 헤드라인의 관계 표현은 헤드라인만 버린다


def test_top_level_title_is_held_to_the_same_rules(sources):
    show = sid(sources, "학교 공연")
    for title in ("학교 공연에 참석했어요", "학교 공연 덕분에 웃은 주"):
        res = ok(run(sources, [art("학교 공연 일정이 있었어요", [show])], title=title))
        assert res.title == "이번 주 우리 가족", title  # 기본 제목으로 바뀐다
    assert (
        ok(run(sources, [art("학교 공연 일정이 있었어요", [show])], title="공연이 있던 주")).title
        == "공연이 있던 주"
    )


def test_describing_an_attendance_schedule_is_not_claiming_attendance(sources):
    show = sid(sources, "학교 공연")
    for text in ("학교 공연 참석 일정이 있었어요", "학교 공연에 참석할 예정이었어요"):
        assert len(ok(run(sources, [art(text, [show])])).items) == 1, text


# ── Opus 리뷰 반영(2026-11-12) ─────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "학교 공연을 보셨어요",
        "학교 공연에 가셨어요",
        "학교 공연에 오셨어요",
        "학교 공연을 봤어요",
        "가족 모임을 가졌어요",
        "치과 진료를 받았어요",
        "영어 수업을 들었어요",
        "행복한 학교 공연이 있었어요",
        "학교 공연이 뿌듯했어요",
        "학교 공연이 화제였어요",  # 일정 표현(있었어요·예정·잡혀·등록·공유)이 없는 문장은 약속에 쓰지 않는다
        "학교 공연 소식이에요",
    ],
)
def test_more_event_wording_that_is_not_a_plain_schedule_is_blocked(sources, text):
    assert isinstance(run(sources, [art(text, [sid(sources, "학교 공연")])]), Failed), text


def test_title_with_an_adverb_or_passive_cannot_hide_the_activity(sources):
    visit = sid(sources, "할머니 댁 방문")
    for text in (
        "할머니 댁 방문 잘 했어요",
        "할머니 댁 방문됐어요",
        "할머니 댁 방문이 무사히 됐어요",
    ):
        assert isinstance(run(sources, [art(text, [visit])]), Failed), text


def test_a_visit_scheduled_with_a_particle_is_a_schedule_not_an_activity(sources):
    show = sid(sources, "학교 공연")
    for text in ("학교 공연 참석이 예정되어 있었어요", "학교 공연 관람이 예정되어 있었어요"):
        assert len(ok(run(sources, [art(text, [show])])).items) == 1, text


def test_a_word_inside_a_title_is_not_a_relation():
    srcs = build_sources([rec("todo", "a", "이어폰 사기", D10), rec("todo", "b", "책 사기", D10)])
    res = ok(run(srcs, [art("이어폰과 책 사기를 마쳤어요", [srcs[0].id, srcs[1].id])]))
    assert len(res.items) == 1


def test_articles_with_the_same_sources_are_not_repeated(sources):
    """같은 근거만 인용한 기사를 되풀이하면 다른 근거의 기사가 상한에 밀려나므로 먼저 나온 것만 남긴다."""
    two = build_sources([rec("event", "a", "치과 모임", D10), rec("todo", "b", "빨래", D11)])
    res = ok(
        run(
            two,
            [
                art("치과 모임이 있었어요", [two[0].id]),
                art("치과 모임이 잡혀 있었어요", [two[0].id]),
                art("빨래를 마쳤어요", [two[1].id]),
            ],
        )
    )
    assert [i.source_ids for i in res.items] == [(two[0].id,), (two[1].id,)]


def test_headline_length_ignores_the_pseudonym_token_length():
    srcs = build_sources([rec("event", "a", "[PERSON_1] [PERSON_2] 저녁 식사", D10)])
    headline = "[PERSON_1]와 [PERSON_2]의 저녁 식사 소식"
    assert len(headline) > 30  # 토큰이 길어서 그대로 재면 넘는다(복원하면 짧다)
    res = ok(
        run(
            srcs,
            [art("[PERSON_1] [PERSON_2] 저녁 식사가 있었어요", [srcs[0].id], headline=headline)],
        )
    )
    assert res.items[0].headline == headline


def test_known_limit_completion_wording_on_a_todo_is_blocked_when_an_event_is_cited(sources):
    """한계(안전한 쪽의 오탐): 같은 기사가 약속도 인용하면, 할 일에만 붙은 '마쳤어요'도 막는다(절 단위 구분은 하지 않는다)."""
    td, visit = sid(sources, "분리수거"), sid(sources, "할머니 댁 방문")
    assert isinstance(
        run(sources, [art("분리수거를 마쳤고 할머니 댁 방문 일정이 있었어요", [td, visit])]), Failed
    )


# ── 기사 모드가 아니면 기존 동작 그대로 ───────────────────────


def test_default_mode_keeps_the_old_behaviour(sources):
    res = validate(
        {
            "title": "t",
            "items": [
                {"text": "학교 공연을 다녀왔어요", "source_ids": [sid(sources, "학교 공연")]}
            ],
        },
        sources,
        [],
    )
    assert (
        isinstance(res, Validated) and res.items[0].role is None and res.items[0].category is None
    )
