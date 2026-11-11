"""탐지기 시험. 모든 번호·이름은 시험용 합성 값이다."""

import pytest

from app.shared.privacy.detectors import _luhn_ok, _rrn_checksum_ok, detect
from app.shared.privacy.types import RISK_BY_KIND, Kind, Risk


def found(text, names=()):
    return [(s.kind, text[s.start : s.end]) for s in detect(text, names)]


def kinds(text, names=()):
    return {k for k, _ in found(text, names)}


# ---------- 전화 ----------
@pytest.mark.parametrize(
    "number",
    [
        "010-1234-5678", "010.1234.5678", "010 1234 5678", "01012345678", "011-123-4567", "016-9876-5432",
        "02-345-6789", "02-1234-5678", "031-123-4567", "051-456-7890", "070-1234-5678", "080-123-4567",
        "+82 10-1234-5678", "+82-10-1234-5678", "+821012345678", "(02) 345-6789", "010 - 1234 - 5678",
    ],
)  # fmt: skip
def test_phone_positive(number):
    assert found(f"번호는 {number} 이야") == [(Kind.PHONE, number)]


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-03 에 만나", "2026.11.03", "오후 3시 30분", "15,000원", "3,200,000원", "1234", "12345",
        "주문번호 202611030012", "수량 100개", "02:30 에 일어나", "12-3456-7890 번 접수", "0000000000",
    ],
)  # fmt: skip
def test_phone_negative(text):
    assert Kind.PHONE not in kinds(text)


# 변형 꼴(2026-11 문서체 측정에서 놓치던 것)
@pytest.mark.parametrize(
    "number",
    [
        "공일공일이삼사오육칠팔", "공일공 일이삼사 오육칠팔", "공일공-일이삼사-오육칠팔", "영일영구팔칠육오사삼이",
        "821012345678", "010-1234-56 78", "010 1234 56 78",
    ],
)  # fmt: skip
def test_phone_variants_are_found(number):
    assert found(f"번호는 {number} 이야") == [(Kind.PHONE, number)]


@pytest.mark.parametrize(
    "text",
    ["전화 1234-5678 로 주세요", "연락처: 12345678", "문의 4321 8765", "휴대폰 번호 5678-1234"],
)
def test_eight_digits_after_phone_context_is_phone(text):
    assert Kind.PHONE in kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "주문번호 1234-5678", "합계 12345678원", "20261103 에 만나", "주문 1234 5678 접수", "승인번호 12345678",
        "금액 1234-5678원 결제", "운송장 821012345678", "사업자등록번호 1234-5678", "번호표 12345678번",
        "재고 12345678", "일이삼사오육칠팔구 순서대로", "전화 20261103",
    ],
)  # fmt: skip
def test_phone_variants_do_not_flag_order_numbers_amounts_or_dates(text):
    assert Kind.PHONE not in kinds(text)


def test_phone_not_part_of_longer_digits():
    assert Kind.PHONE not in kinds("번호 010123456789012 야")


# ---------- 이메일 ----------
def test_email():
    assert found("메일 abc.def+x@gmail.com으로 보내줘") == [(Kind.EMAIL, "abc.def+x@gmail.com")]
    assert found("a@b.co.kr 와 c_d@naver.com") == [
        (Kind.EMAIL, "a@b.co.kr"),
        (Kind.EMAIL, "c_d@naver.com"),
    ]
    assert Kind.EMAIL not in kinds("골뱅이 naver.com 이나 @home 같은 말")


# ---------- 주민등록번호 ----------
def make_rrn(front="900101", gender=1, body5="23456"):
    base = f"{front}{gender}{body5}"
    w = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    s = sum(int(d) * x for d, x in zip(base, w, strict=True))
    check = (11 - s % 11) % 10
    return base + str(check)


def test_rrn_checksum_valid_high_score():
    num = make_rrn()
    assert _rrn_checksum_ok(num)
    spans = detect(f"주민번호 {num[:6]}-{num[6:]} 야")
    assert [(s.kind, s.score) for s in spans] == [(Kind.RRN, 0.97)]


def test_rrn_foreigner_checksum():
    base = "900101" + "5" + "23456"
    w = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    s = sum(int(d) * x for d, x in zip(base, w, strict=True))
    num = base + str(((11 - s % 11) % 10 + 2) % 10)
    assert _rrn_checksum_ok(num)


def test_rrn_bad_checksum_still_detected_with_low_score():
    num = make_rrn()
    bad = num[:-1] + str((int(num[-1]) + 1) % 10)
    assert not _rrn_checksum_ok(bad)
    spans = detect(f"{bad[:6]}-{bad[6:]}")
    assert len(spans) == 1 and spans[0].kind is Kind.RRN and spans[0].score < 0.7
    assert RISK_BY_KIND[Kind.RRN] is Risk.HIGH


@pytest.mark.parametrize(
    "text", ["991399-1234567", "900230-1234567", "900101-9234567", "9001011234567890"]
)
def test_rrn_invalid_date_or_gender(text):
    assert Kind.RRN not in kinds(text)


# ---------- 카드 ----------
def luhn_number(prefix, length):
    body = prefix + "1" * (length - len(prefix) - 1)
    for check in "0123456789":
        if _luhn_ok(body + check):
            return body + check


def test_card_luhn():
    num = luhn_number("4539", 16)
    assert found(f"카드 {num[:4]} {num[4:8]} {num[8:12]} {num[12:]} 야")[0][0] is Kind.CARD
    assert found(f"카드 {num[:4]}-{num[4:8]}-{num[8:12]}-{num[12:]}")[0][0] is Kind.CARD
    assert found(f"카드 {num}")[0][0] is Kind.CARD
    amex = luhn_number("37", 15)
    assert found(f"{amex[:4]}-{amex[4:10]}-{amex[10:]}")[0][0] is Kind.CARD


def test_card_negative():
    bad = luhn_number("4539", 16)
    bad = bad[:-1] + str((int(bad[-1]) + 1) % 10)
    assert Kind.CARD not in kinds(f"번호 {bad}")  # Luhn 실패
    assert Kind.CARD not in kinds("주문번호 2026110312345678")  # 연도로 시작
    assert Kind.CARD not in kinds("1234 5678 9012 3456 은 아니야")  # Luhn 실패


# Luhn 실패 번호의 단계 규칙: 형식(구분자)·문맥이 확실하면 낮은 점수로 가린다. 시험용 합성 값이다.
def card_scores(text):
    return [s.score for s in detect(text) if s.kind is Kind.CARD]


@pytest.mark.parametrize(
    "text",
    [
        "카드번호 4512-4516-1112-0055",
        "4512 4516 1112 0055 로 결제해줘",
        "카드번호 4512451611120055",
        "결제는 4512451611120055 로 했어",
    ],
)
def test_card_luhn_fail_masked_with_low_score(text):
    assert not _luhn_ok("4512451611120055")
    scores = card_scores(text)
    assert len(scores) == 1 and scores[0] < 0.7  # 가리기만 하고 메시지 통째 제외는 아님


@pytest.mark.parametrize(
    "text",
    [
        "4512451611120055",  # 문맥도 구분자도 없는 순수 숫자
        "번호 4512451611120055 야",
        "운송장 4512451611120055",
        "주문번호 4512451611120055",
        "주문번호 4512-4516-1112-0055",  # 구분자가 있어도 주문번호 문맥이면 버림
        "카드 주문번호 4512451611120055",
        "주문번호 2026110312345678",  # 연도로 시작 (발급 대역 밖)
        "카드번호 2026-1103-1234-5678",
    ],
)
def test_card_luhn_fail_without_strong_signal_ignored(text):
    assert Kind.CARD not in kinds(text)


def test_card_score_order_luhn_pass_above_fail():
    ok = luhn_number("4539", 16)
    bad = ok[:-1] + str((int(ok[-1]) + 1) % 10)

    def fmt(n):
        return f"{n[:4]}-{n[4:8]}-{n[8:12]}-{n[12:]}"

    (pass_score,) = card_scores(f"카드 {fmt(ok)}")
    (fail_score,) = card_scores(f"카드 {fmt(bad)}")
    assert pass_score == 0.95 and 0.5 <= fail_score < 0.7 < pass_score
    assert card_scores(f"카드 {ok}") == [0.95] and card_scores(ok) == [0.65]  # 기존 점수 유지
    assert card_scores(f"카드 {bad}") == [0.5] and not card_scores(bad)  # 끊지 않음: 문맥 있을 때만


# ---------- 계좌 ----------
@pytest.mark.parametrize(
    "text,value",
    [
        ("국민은행 123456-01-123456 으로 입금", "123456-01-123456"),
        ("신한 110-123-456789 보내줘", "110-123-456789"),
        ("계좌번호 1002345678901 야", "1002345678901"),
        ("카카오뱅크 3333-12-3456789", "3333-12-3456789"),
        ("우리은행 1002-123-456789", "1002-123-456789"),
    ],
)
def test_account_with_context(text, value):
    assert (Kind.ACCOUNT, value) in found(text)


@pytest.mark.parametrize(
    "text",
    [
        "주문번호 1234567890123", "운송장 123-4567-8901", "송장 1234567890", "우리 1234567890123 번호",
        "계좌 이체가 안 돼", "국민은행 3시에 만나", "2026-11-03 계좌 확인",
    ],
)  # fmt: skip
def test_account_negative(text):
    assert Kind.ACCOUNT not in kinds(text)


def test_account_phone_shape_is_phone():
    assert found("국민은행 앞에서 010-1234-5678") == [(Kind.PHONE, "010-1234-5678")]


# ---------- 비밀 정보: 값만 구간 ----------
@pytest.mark.parametrize(
    "text,value",
    [
        ("와이파이 비밀번호는 abc12345! 야", "abc12345!"),
        ("비번: 9988", "9988"),
        ("인증번호 482913입니다", "482913"),
        ("OTP=123456", "123456"),
        ("password: Hunter22", "Hunter22"),
        ("PIN 2580 입력", "2580"),
        ("핀번호 1357", "1357"),
    ],
)
def test_secret_value_only(text, value):
    assert [t for k, t in found(text) if k is Kind.SECRET] == [value]


def test_secret_negative():
    assert Kind.SECRET not in kinds("비밀번호 바꿔야 하는데 귀찮다")
    assert Kind.SECRET not in kinds("인증번호가 안 와")
    assert Kind.SECRET not in kinds("비번 2024년까지 유효")
    assert Kind.SECRET not in kinds("pinterest 에서 봤어")
    assert Kind.SECRET not in kinds("cvc 987")  # 4자 미만은 값으로 보지 않는다(알려진 한계)


def test_secret_span_excludes_keyword():
    text = "비밀번호는 abc12345 야"
    (span,) = detect(text)
    assert text[span.start : span.end] == "abc12345"


# ---------- 주소 ----------
@pytest.mark.parametrize(
    "addr",
    [
        "테헤란로 152", "서울시 강남구 테헤란로 152", "세종대로 110-1", "판교역로 235", "가로수길 12", "중앙로12길 5",
        "역삼동 123-45", "서초동 12번지", "101동 1203호", "경기도 성남시 분당구 정자동 12-3", "서울 강남구",
        "서울시 강남구 테헤란로 152 101동 1203호",
    ],
)  # fmt: skip
def test_address_positive(addr):
    assert found(f"우리 집은 {addr} 야") == [(Kind.ADDRESS, addr)]


@pytest.mark.parametrize(
    "text",
    [
        "강남역에서 만나", "서울 가는 기차", "부산 여행", "제주도 항공권", "그대로 5개", "집으로 3명", "운동 30분", "예약하려면 02-748",
        "서울 친구랑", "한강로 3가 쪽", "5호선 타", "3층 301호", "행동 3가지",
    ],
)  # fmt: skip
def test_address_negative(text):
    assert Kind.ADDRESS not in kinds(text)


# ---------- 이름 ----------
def test_person_dictionary_with_particle_only_name_span():
    text = "김민수가 오고 이영희에게 말했고 박지후한테도 알렸어"
    names = ("김민수", "이영희", "박지후")
    assert found(text, names) == [
        (Kind.PERSON, "김민수"),
        (Kind.PERSON, "이영희"),
        (Kind.PERSON, "박지후"),
    ]


def test_person_given_name_alias_maps_to_full_name():
    spans = detect("민수야 밥 먹자", ("김민수",))
    assert len(spans) == 1 and spans[0].canonical == "김민수"


def test_person_dictionary_boundary():
    assert Kind.PERSON not in kinds("김민수기념관에 갔어", ("김민수",))
    assert Kind.PERSON not in kinds("지후드라마", ("박지후",))


def test_kinship_not_masked_even_if_in_names():
    assert detect("엄마 아빠 어디야", ("엄마", "아빠")) == []


def test_person_honorific_heuristic_low_score():
    spans = detect("김철수님께 전화하고 박영숙씨도 불러")
    assert [(s.kind, s.score) for s in spans] == [(Kind.PERSON, 0.5)] * 2
    assert RISK_BY_KIND[Kind.PERSON] is Risk.LOW


@pytest.mark.parametrize(
    "text",
    [
        "김치 먹자",
        "박수 쳐줘",
        "이사 가자",
        "정리 좀 해",
        "고객님 오세요",
        "선생님이 왔어",
        "이사님 오셨어",
        "사장님 감사해요",
        "고추씨 사와",
        "부모님 오신대",
    ],
)
def test_person_negative_common_words(text):
    assert Kind.PERSON not in kinds(text)


def test_person_without_title_or_dictionary_is_missed():
    assert detect("철수한테 말해") == []  # 알려진 한계


# ---------- 겹침·위험도 ----------
def test_overlap_high_risk_wins():
    text = "계좌 3333-12-3456789 카카오뱅크"
    assert [k for k, _ in found(text)] == [Kind.ACCOUNT]


def test_results_sorted_and_non_overlapping():
    text = "김민수 010-1234-5678 kim@example.com 서울시 강남구 테헤란로 152 비번 abcd1234"
    spans = detect(text, ("김민수",))
    assert [s.kind for s in spans] == [
        Kind.PERSON,
        Kind.PHONE,
        Kind.EMAIL,
        Kind.ADDRESS,
        Kind.SECRET,
    ]
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:], strict=False))


def test_empty_and_plain_text():
    assert detect("") == []
    assert detect("안녕 오늘 뭐 해?") == []


# ---------- 주소 뒤 (동 이름) · 층 · 호수 (2026-11 보강)
@pytest.mark.parametrize(
    ("text", "whole"),
    [
        ("서울 강남구 소나무로 152번길 9, 3층 301호", "서울 강남구 소나무로 152번길 9, 3층 301호"),
        ("보라매로 457 4층 1691호", "보라매로 457 4층 1691호"),
        ("마포구 다람쥐로 77 301호", "다람쥐로 77 301호"),
        ("테헤란로 303 5층", "테헤란로 303 5층"),
        ("서울 강남구 테헤란로 303 B1층 12호", "서울 강남구 테헤란로 303 B1층 12호"),
        ("강남구 테헤란로 152 지하 1층 B101호", "테헤란로 152 지하 1층 B101호"),
        ("서울시 강남구 역삼동 123-45 2층", "서울시 강남구 역삼동 123-45 2층"),
        ("경기 성남시 분당구 정자일로 95 (정자동) 12층 1203호", "경기 성남시 분당구 정자일로 95 (정자동) 12층 1203호"),
    ],
)  # fmt: skip
def test_address_unit_tail_is_included(text, whole):
    assert [t for k, t in found(text) if k == Kind.ADDRESS] == [whole]


@pytest.mark.parametrize(
    "text",
    ["테헤란로 5층 회의실", "중앙로 2호선 근처", "사과 3개 5층 식당 301호선", "서울 강남구 테헤란로 303 에서 만나"],
)  # fmt: skip
def test_address_unit_tail_does_not_swallow_ordinary_words(text):
    for k, t in found(text):
        if k == Kind.ADDRESS:
            assert "층" not in t and "호" not in t


def test_address_number_followed_by_next_line_word_is_not_taken_as_a_unit():
    # '412' 뒤 줄바꿈 다음 '주문번호'의 '주'를 수량 단위로 오해해 주소를 놓치던 문제
    text = "배달주소 대전 서구 보라매로 412\n주문번호 1244051092"
    assert [t for k, t in found(text) if k == Kind.ADDRESS] == ["대전 서구 보라매로 412"]
