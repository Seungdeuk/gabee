"""자유 글·JSON API 보강 시험: 주소+전화, 좌표 쌍, 키 충돌, 숫자 키, 투명 문자, 세션 보호, 자리표시 검사."""

import dataclasses
import re
import time

import pytest

import app.shared.privacy.freetext as ft
from app.shared.privacy import (
    ANALYSIS,
    TOPICS,
    Kind,
    PrivacySession,
    contains_placeholders,
    detect,
    new_session,
    prepare_json,
    prepare_text,
    prepare_transcript,
)


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - start


# ---------- 주소 뒤 전화번호 ----------
@pytest.mark.parametrize(
    "text",
    [
        "서울시 강남구 테헤란로 010-1234-5678",
        "서울시 강남구 테헤란로 010-1234-5678 로 연락",
        "서울시 강남구 테헤란로\n010-1234-5678",
        "서울시 강남구 테헤란로 152 010-1234-5678",
        "서울시 강남구 테헤란로 02-1234-5678",
        "서울시 강남구 역삼동 010-1234-5678",
    ],
)
def test_phone_after_address_is_not_swallowed(text):
    out, sess = prepare_text(text)
    assert "5678" not in out and "1234" not in out and "010" not in out
    assert sess.counts_by_kind.get("PHONE") == 1
    restored = sess.restore_text(out).value  # 주소는 복원돼도 전화 끝자리는 되살아나지 않는다
    assert "5678" not in restored and "(연락처)" in restored
    with prepare_transcript(
        [(1, "가", text)], [], ANALYSIS
    ) as prep:  # 기존 줄 단위 API 도 같은 탐지기
        assert "5678" not in prep.lines[0].text


def test_normal_road_addresses_unchanged():
    for text in ("서울시 강남구 테헤란로 152", "테헤란로 152-3", "테헤란로 152 101동 1203호"):
        spans = detect(text)
        assert [s.kind for s in spans] == [Kind.ADDRESS]
        assert spans[0].end == len(text)
    out, sess = prepare_text("우편번호 06236 서울시 강남구 테헤란로 152 101동 1203호")
    assert "PHONE" not in sess.counts_by_kind and "ACCOUNT" not in sess.counts_by_kind
    assert "152" not in out and "1203" not in out
    assert sess.counts_by_kind["ADDRESS"] == 1


# ---------- 키 충돌 / 숫자 키 / precision ----------
def test_pseudonymize_keys_collision_raises_instead_of_overwriting():
    with pytest.raises(ValueError):
        prepare_json({"김민수": 1, "민수": 2}, members=[("김민수", "민수")], pseudonymize_keys=True)
    # 사용자가 쓴 토큰 모양 키는 무력화돼 가명화 토큰과 부딪치지 않는다
    out0, _ = prepare_json(
        {"[PERSON_1]": 1, "김민수": 2}, members=["김민수"], pseudonymize_keys=True
    )
    assert out0 == {"‹PERSON_1›": 1, "[PERSON_1]": 2}
    out, _ = prepare_json(
        {"김민수": 1, "이영희": 2}, members=["김민수", "이영희"], pseudonymize_keys=True
    )
    assert out == {"[PERSON_1]": 1, "[PERSON_2]": 2}


def test_numbers_round_keeps_ids_and_supports_number_keys():
    data = {
        "id": 123456,
        "user_id": 98765,
        "userId": 54321,
        "amount": 123456,
        "items": [{"id": 777777, "price": 45678}],
    }
    out, _ = prepare_json(data, numbers="round")
    assert out["id"] == 123456 and out["user_id"] == 98765 and out["userId"] == 54321
    assert out["amount"] == 120000 and out["items"][0] == {"id": 777777, "price": 46000}
    only, _ = prepare_json(data, numbers="round", number_keys=["amount"])
    assert only["amount"] == 120000 and only["items"][0] == {"id": 777777, "price": 45678}
    assert only["id"] == 123456
    keep, _ = prepare_json(data)  # 기본(keep) 동작은 그대로
    assert keep == data


@pytest.mark.parametrize("bad", [1.5, -1, 7, True, "2"])
def test_coordinate_precision_strict_in_json_and_text(bad):
    with pytest.raises(ValueError):
        prepare_json({"lat": 1.23456}, coordinate_precision=bad)
    with pytest.raises(ValueError):
        new_session().prepare_text("37.566535,126.977969", coordinate_precision=bad)


# ---------- 좌표 쌍 ----------
def test_coordinate_pairs_outside_coordinate_keys():
    out, s = prepare_json(
        {"location": [37.56789, 126.97899], "pt": (37.5678, 127.0399), "geo": [126.97899, 37.56789]}
    )
    assert out["location"] == [37.56, 126.97] and out["pt"] == (37.56, 127.03)
    assert out["geo"] == [126.97, 37.56]  # [경도, 위도] 순서(GeoJSON)도 범위로 알아본다
    assert s.coordinates_generalized == 3
    out2, _ = prepare_json(
        {
            "s": "현위치 37.566535,126.977969 입니다",
            "t": "좌표 [37.5665; 126.9780]",
            "u": "위도 경도 37.5665 126.9780",
            "v": "정밀 37.566535 126.977969",
            "w": "126.977969, 37.566535",
            "x": "https://maps.example.com/?q=37.5665,126.9780",
        }
    )
    assert out2["s"] == "현위치 37.56, 126.97 입니다"
    assert out2["t"] == "좌표 [37.56, 126.97]"
    assert out2["u"] == "위도 경도 37.56, 126.97"
    assert out2["v"] == "정밀 37.56, 126.97"
    assert out2["w"] == "126.97, 37.56"  # 경도가 먼저(앞 수 > 90)
    assert out2["x"].endswith("?q=37.56, 126.97")
    txt, sess = prepare_text("집은 37.566535,126.977969 쯤, 회사는 -33.868812, 151.209312")
    assert txt == "집은 37.56, 126.97 쯤, 회사는 -33.86, 151.20"
    assert sess.coordinates_generalized == 2


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-26 일정",
        "버전 1.2.3 과 1.2.4",
        "금액 1,234.5678 원",
        "12.34, 56.78",
        "평점 4.5 와 3.5",
        "좌표 아님 123.4567, 245.6789",  # 단서가 있어도 지구상 유효한 쌍이 아니면 그대로
        "37.5665.126.9780",
        "가격 12.5 14.25",
        "환율 1.3456 1.4567",  # 단서 없는 4자리 소수 두 개(환율)
        "금리 3.1250, 3.2500",
        "체온 36.5000 37.1000",
        "비교 12.3456, 98.7654",
        "v1.23456 2.34567",  # 영문자 뒤에서 시작
        "a37.56653 126.97799",
        "ver2.34567, 3.45678",
        "확률 0.12345, 0.98765",  # 정밀해도 0~1 값만
        "성공률 91.2345% 92.3456%",
    ],
)
def test_coordinate_rule_has_no_false_positive(text):
    out, sess = prepare_text(text)
    assert out == text
    assert sess.coordinates_generalized == 0


def test_coordinate_text_cue_is_local():
    far = "위치 정보는 없음. " + "가" * 60 + " 환율 37.5665 126.9780"
    out, _ = prepare_text(far)
    assert out == far  # 단서가 멀면 4자리 쌍은 그대로


def test_json_float_pair_not_coordinate_without_cue_or_precision():
    data = {
        "a": [37.5, 127.0],
        "b": [123.4567, 245.6789],
        "c": [1.0, 2.0, 3.0],
        "probs": [0.12345, 0.98765],
        "weights": [12.345, 56.789],
        "scores": [37.5665, 126.9780],  # 단서 없는 4자리
    }
    out, s = prepare_json(data)
    assert out == data
    assert s.coordinates_generalized == 0
    out2, s2 = prepare_json({"x": [37.566535, 126.977969], "y": [126.977969, 37.566535]})
    assert out2 == {
        "x": [37.56, 126.97],
        "y": [126.97, 37.56],
    }  # 단서 없어도 정밀(소수 5자리 이상, 10 이상)
    assert s2.coordinates_generalized == 2
    out3, _ = prepare_json({"position": [37.5665, 126.978], "latlng": [37.5665, 126.9781]})
    assert out3["position"] == [37.5665, 126.978]  # 소수 3자리는 쌍으로 보지 않음
    assert out3["latlng"] == [37.56, 126.97]


def test_coordinate_regex_is_fast():
    for text in ("1." + "1" * 100_000, "0.1234 " * 20_000, "1.2345," * 20_000, "-" * 100_000):
        sess = new_session()
        assert timed(sess.prepare_text, text) < 1.5
        sess.close()


# ---------- 자리표시 검사 ----------
def test_contains_placeholders():
    bad_values = [
        "(연락처)", "연락은 (이메일) 로", "(주소)", "(사람)", "(알 수 없는 항목)", "(민감 정보)",
        "[RRN]", "[CARD] 결제", "[PERSON_3]", "[ADDR_1] 집", "‹PHONE_1›",
        {"memo": ["ok", {"x": "[SECRET]"}]}, {"(연락처)": 1}, ("a", "(주소)"),
        "( 연락처 )", "（연락처）", "( 알 수 없는 항목 )", "[ADDRESS_1]", "[NAME_1]", "[ person_1 ]", "(PERSON_1)",
        "<PHONE_1>", "{PERSON_1}", "［ADDR_2］", "[PERSON_1\u200b]", "[PER\u200bSON_1]", "PERSON_1", "PHONE_12 로",
        "[rrn]", "［ＲＲＮ］", "(EMAIL_3)",
    ]  # fmt: skip
    for bad in bad_values:
        assert contains_placeholders(bad), bad
    ok_values = [
        "김민수 병원 3시", "대괄호 [메모] 와 (참고)", {"a": [1, 2.5, None, True, "일정"]}, 5, None,
        "PERSONAL_1", "my_PHONE_book", "CARDINAL_2", "(주소록)", "[2026-10-26]",
    ]  # fmt: skip
    for ok in ok_values:
        assert not contains_placeholders(ok), ok
    assert contains_placeholders(
        "회의 (주소) 확인"
    )  # 사용자가 쓴 글도 True: 안전한 방향의 오탐(문서에 명시)
    out, sess = prepare_text("김민수 010-1234-5678", members=["김민수"])
    assert contains_placeholders(
        sess.restore_text(out).value
    )  # '(연락처)' 가 남았다 -> 쓰기 도구는 거부
    assert not contains_placeholders(sess.restore_text("[PERSON_1] 만남").value)
    sess.close()


def test_contains_placeholders_is_fast():
    for text in (
        "[" + " " * 100_000,
        "[PERSON" + " " * 100_000 + "_",
        "(" * 100_000,
        "PERSON_" * 20_000,
    ):
        assert timed(contains_placeholders, text) < 1.5


# ---------- 투명 문자(소스에는 이스케이프 표기만 쓴다) ----------
def test_invisible_characters_do_not_hide_numbers_or_names():
    out, sess = prepare_text(
        "0\u200b10-1234-5678 / 김\u200d민수 / 9001\ufeff01-1234568", members=["김민수"]
    )
    assert out == "[PHONE_1] / [PERSON_1] / [RRN]"
    assert detect("a\u200b") == [] and detect("\u200b") == []


@pytest.mark.parametrize(
    "ch",
    ["\u00ad", "\u034f", "\u180e", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u2060", "\u2061",
     "\u2062", "\u2063", "\u2064", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067",
     "\u2068", "\u2069", "\ufeff"],
)  # fmt: skip
def test_each_invisible_character_is_stripped_before_detection(ch):
    phone = f"010{ch}-1234{ch}-5678"
    spans = detect(f"전화 {phone} 끝")
    assert [(s.kind, s.start, s.end) for s in spans] == [(Kind.PHONE, 3, 3 + len(phone))]
    out, _ = prepare_text(f"전화 {phone} 끝")
    assert out == "전화 [PHONE_1] 끝"


def test_invisible_boundaries_exact_output():
    sh = "\u00ad"
    out, _ = prepare_text(f"앞{sh}010{sh}1234{sh}5678{sh}뒤")
    assert (
        out == f"앞{sh}[PHONE_1]{sh}뒤"
    )  # 번호 안쪽 투명 문자는 번호와 함께 사라지고, 바깥쪽은 남는다
    out2, _ = prepare_text("\u200e010-1234-5678\u200f")
    assert out2 == "\u200e[PHONE_1]\u200f"
    out3, _ = prepare_text("010\u200e-1234-5678", policy=ANALYSIS)
    assert out3 == "[PHONE_1]"
    out4, _ = prepare_text("\u200b\u200b\u200b")
    assert out4 == "\u200b\u200b\u200b"  # 투명 문자만 있는 글은 그대로


# ---------- 세션 ----------
def test_session_is_slotted_and_not_replaceable():
    sess = new_session(members=["김민수"])
    with pytest.raises(TypeError):
        vars(sess)
    assert not hasattr(sess, "__dict__")
    with pytest.raises(TypeError):
        dataclasses.replace(sess)  # 대응표를 공유하는 사본을 만들 수 없다
    with pytest.raises(AttributeError):
        sess.new_attr = 1
    sess.close()


def test_exception_closes_new_session():
    class Bad:
        pass

    created: list[PrivacySession] = []
    original = ft.new_session

    def spy(*a, **k):
        s = original(*a, **k)
        created.append(s)
        return s

    ft.new_session = spy
    try:
        with pytest.raises(TypeError):
            prepare_json({"a": "010-1234-5678", "b": Bad()})
        with pytest.raises(TypeError):
            prepare_text(123)
    finally:
        ft.new_session = original
    assert len(created) == 2
    for s in created:
        assert s.pseudonymizer.size == 0
        with pytest.raises(RuntimeError):
            s.prepare_text("010-1234-5678")


# ---------- 일상 말 오탐 방지 / id 키 / number_keys ----------
@pytest.mark.parametrize(
    "text",
    [
        "이 번호로 010-1234-5678",
        "전화로 010-1234-5678",
        "문자로 010 1234 5678",
        "학교로 031-123-4567",
        "회사로 02-1234-5678",
        "집으로 010-1234-5678 연락해",
    ],
)
def test_everyday_words_before_phone_are_not_addresses(text):
    assert [s.kind for s in detect(text)] == [Kind.PHONE]
    out, sess = prepare_text(text)
    assert "ADDRESS" not in sess.counts_by_kind and sess.counts_by_kind == {"PHONE": 1}
    phone = re.search(r"0\d{1,2}[- ]\d{3,4}[- ]\d{4}", text).group(0)
    expected = text.replace(phone, "[PHONE_1]")
    assert out == expected
    for policy in (ANALYSIS, TOPICS):
        with prepare_transcript([(1, "가", text)], [], policy) as prep:
            assert prep.lines[0].text == expected


def test_address_plus_phone_still_phone_whole():
    for text in (
        "서울시 강남구 테헤란로 010-1234-5678",
        "서울시 강남구 테헤란로\n010-1234-5678",
        "서울시 강남구 테헤란로 152 010-1234-5678",
    ):
        spans = detect(text)
        assert [s.kind for s in spans] == [Kind.ADDRESS, Kind.PHONE]
        assert text[spans[1].start : spans[1].end] == "010-1234-5678"


def test_id_like_keys_preserved_including_uppercase_and_plural():
    data = {
        "userID": 123456, "memberID": 223456, "member_ids": [123456, 234567], "ids": [345678],
        "userIds": [456789], "ID": 567890, "amount": 123456, "valid": 123456,
    }  # fmt: skip
    out, _ = prepare_json(data, numbers="round")
    for k in ("userID", "memberID", "member_ids", "ids", "userIds", "ID"):
        assert out[k] == data[k], k
    assert out["amount"] == 120000 and out["valid"] == 120000  # 'valid' 는 id 키가 아니다


def test_number_keys_apply_to_nested_dict_under_listed_key():
    data = {
        "amount": {"value": 12345, "id": 99999},
        "other": {"value": 12345},
        "items": [{"amount": 45678}],
    }
    out, _ = prepare_json(data, numbers="round", number_keys=["amount"])
    assert out["amount"] == {
        "value": 12000,
        "id": 99999,
    }  # 지정한 키 아래 중첩 값도 뭉개고 id 는 보존
    assert out["other"] == {"value": 12345}
    assert out["items"] == [{"amount": 46000}]
