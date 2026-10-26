"""호칭 앞 공백 이름, 같은 사람의 여러 표기(표시 이름) 묶기, 응답에 남은 토큰 모양 정리 시험. 모든 이름은 합성 값이다."""

import pytest

from app.shared.privacy import ANALYSIS, Kind, detect, prepare_transcript, restore_json
from app.shared.privacy.pseudonymizer import scrub_leftovers


def persons(text):
    return [text[s.start : s.end] for s in detect(text) if s.kind is Kind.PERSON]


@pytest.mark.parametrize(
    "text, name",
    [
        ("홍길동 선생님 생일 축하해", "홍길동"),
        ("김철수 씨 오셨어요", "김철수"),
        ("박영희 님께 전달해줘", "박영희"),
        ("최민수 님이 말했어", "최민수"),
    ],
)
def test_name_with_one_space_before_title_is_masked(text, name):
    assert persons(text) == [name]


@pytest.mark.parametrize(
    "text",
    [
        "이사 님 오셨다",
        "고객 님 안녕하세요",
        "사장 님이 말씀하셨어",
        "선생 님 감사합니다",
        "가족 모두 님 안녕",
        "사용자 님 확인해 주세요",
        "신청자 씨 오셨어요",
        "정대표 님 오셨어요",
        "어르신 님 오셨어요",
        "고기 양이 많다",
        "고추장 양이 적어",
        "한우 씨 말려",
        "손님 오셔서 정신없어",
    ],
)
def test_spaced_title_with_common_words_is_not_masked(text):
    assert persons(text) == []


def test_unspaced_title_behaviour_is_unchanged():
    assert persons("김과장님 오셨어") == ["김과장"]  # 성+직함은 이름 꼴이라 가린다(기존 의도)
    assert persons("홍길동님께") == ["홍길동"]


# ---------- 같은 사람의 여러 표기 ----------
def test_display_name_and_real_name_share_one_token():
    rows = [
        (1, "이수진", "수지니야 장보기 부탁해"),
        (2, "박지민", "수진이가 답했어"),
        (3, "이수진", "알겠어 지민아"),
    ]
    names = [("박지민",), ("이수진", "수지니")]
    with prepare_transcript(rows, names, ANALYSIS) as prep:
        sp = [line.speaker for line in prep.lines]
        assert sp[0] == sp[2] and sp[0] != sp[1]
        sujin = sp[0]
        assert sujin in prep.lines[1].text  # 본문 '수진이가' 도 같은 사람
        assert sujin in prep.lines[0].text  # 표시 이름 '수지니야' 도 같은 사람
        assert "수지니" not in prep.lines[0].text
        out = restore_json(prep, {"assignee": sujin})
        assert out.value == {"assignee": "이수진"}  # 대표 이름(실제 이름)으로 복원


def test_alias_grouping_is_deterministic_and_plain_strings_still_work():
    rows = [(1, "이수진", "수지니야"), (2, "박지민", "응")]
    a = prepare_transcript(rows, [("박지민",), ("이수진", "수지니")], ANALYSIS)
    b = prepare_transcript(rows, [("박지민",), ("이수진", "수지니")], ANALYSIS)
    assert [x.text for x in a.lines] == [x.text for x in b.lines]
    c = prepare_transcript(rows, ["이수진", "박지민"], ANALYSIS)  # 이름만 넘기는 기존 방식
    assert c.lines[0].speaker == "[PERSON_1]"
    for p in (a, b, c):
        p.close()


# ---------- 응답에 남은 토큰 모양 ----------
def test_scrub_leftovers_replaces_neutralized_and_fixed_tokens():
    text = "‹PERSON_2› 와 [RRN] 그리고 [CARD] [ACCOUNT] [SECRET] ‹메모›"
    assert (
        scrub_leftovers(text)
        == "(알 수 없는 항목) 와 (민감 정보) 그리고 (민감 정보) (민감 정보) (민감 정보) ‹메모›"
    )


def test_restore_json_scrub_option():
    rows = [
        (1, "이수진", "[PERSON_2] 야 주민번호 900101-1234568 이야"),
        (2, "박지민", "응"),
        (3, "이수진", "음"),
    ]
    with prepare_transcript(rows, ["이수진", "박지민"], ANALYSIS) as prep:
        raw = restore_json(prep, {"s": "‹PERSON_2› [RRN]"})
        assert raw.value == {"s": "‹PERSON_2› [RRN]"}
        cleaned = restore_json(prep, {"s": "‹PERSON_2› [RRN]"}, scrub=True)
        assert cleaned.value == {"s": "(알 수 없는 항목) (민감 정보)"}
