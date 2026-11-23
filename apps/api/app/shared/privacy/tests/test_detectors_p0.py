"""P0 고위험(ACCOUNT·RRN·CARD·SECRET) 비정형 표기 탐지 시험. 모든 번호는 시험용 합성 값이다.

이 시험은 합성 문장에서만 확인한다(모든 입력에서 누출이 없다는 보증이 아니다).
"""

import pytest

from app.shared.privacy.detectors import detect
from app.shared.privacy.policy import ANALYSIS
from app.shared.privacy.pseudonymizer import Pseudonymizer
from app.shared.privacy.types import Kind


def hits(text, kind):
    return [(text[s.start : s.end], s.score) for s in detect(text) if s.kind is kind]


def one(text, kind):
    found = hits(text, kind)
    assert len(found) == 1, (text, found)
    return found[0]


# ---------- 양성: 정규화·구분자·문맥으로 잡아야 하는 표기 ----------
@pytest.mark.parametrize(
    ("text", "value", "min_score"),
    [
        ("계좌 110 123 456789", "110 123 456789", 0.7),  # 공백으로 묶은 계좌
        ("계좌번호 583-칠칠삼-육삼칠오오이 로 보내줘", "583-칠칠삼-육삼칠오오이", 0.7),  # 한글 숫자
        ("계좌번호 구삼칠 칠칠칠 사사칠일이팔 로 보내줘", "구삼칠 칠칠칠 사사칠일이팔", 0.7),
        ("캡처한 통장 10O2-349-74955l", "10O2-349-74955l", 0.7),  # OCR 혼동 + '통장' 단서
        ("캡처한 통장 538O-l9-4232S3", "538O-l9-4232S3", 0.7),
    ],
)
def test_account_unusual_forms_detected_and_blocked(text, value, min_score):
    got, score = one(text, Kind.ACCOUNT)
    assert got == value and score >= min_score  # 정책 임계값 0.7 이상 = 메시지 차단


def test_account_transfer_action_with_account_shape_is_mask_only():
    got, score = one("110-123-456789 로 보내줘", Kind.ACCOUNT)
    assert got == "110-123-456789" and 0.5 <= score < 0.7  # 가리기만, 차단 아님


def test_account_weak_cue_with_hyphen_shape_current_ladder_is_pinned():
    # 문서상 '입금·송금' 약한 단서는 가리기만이지만 하이픈 가산(+0.1)으로 0.7 이 되어 실제로는 차단된다(기존 동작, 이번 변경 아님).
    _, score = one("입금 110-123-456789", Kind.ACCOUNT)
    assert score == pytest.approx(0.7)


def test_account_trailing_amount_is_not_swallowed():
    got, _ = one("계좌 110 123 456789 1000원", Kind.ACCOUNT)
    assert got == "110 123 456789"


@pytest.mark.parametrize(
    "text",
    [
        "110-123-456789",  # 단서도 행동 말도 없는 번호
        "주문번호 110 123 456789",
        "2026-11-03 회의 2026 11 03",
        "전화 010 1234 5678 로 줘",  # 전화번호는 계좌가 아니다
        "택배 운송장 110-123-456789 로 보내줘",  # 운송장 문맥
        "금액은 계좌 110 123 4567 원",  # 금액
    ],
)
def test_account_negatives(text):
    assert not hits(text, Kind.ACCOUNT)


# ---------- RRN ----------
@pytest.mark.parametrize(
    "text",
    [
        "주민번호 오이공육일일-사육삼삼일칠공 야",  # 한글 숫자(체크섬 통과)
        "주민번호 육칠공오공팔-삼구오구구이육 야",
        "신분증 스캔: 주민번호 45l209-323B623",  # OCR 혼동
        "신분증 스캔: 주민번호 S5O216-438O327",
    ],
)
def test_rrn_normalized_forms_detected_with_high_score(text):
    _, score = one(text, Kind.RRN)
    assert score == pytest.approx(0.97)


def test_rrn_invalid_date_policy_ladder():
    # 날짜 무효 + 체크섬 통과 + 주민번호 단서: 차단(0.75)
    got, score = one("주민등록번호는 321326-4930011 입니다", Kind.RRN)
    assert got == "321326-4930011" and score == pytest.approx(0.75)
    # 날짜 무효 + 체크섬 통과 + 형태(하이픈)만: 가리기만(0.6)
    got, score = one("본인확인 300332-4560920 다시 해줘", Kind.RRN)
    assert got == "300332-4560920" and score == pytest.approx(0.6)
    # 날짜 무효 + 체크섬 불일치 + 단서: 가리기만(0.5)
    _, score = one("주민번호 321326-4930012", Kind.RRN)
    assert score == pytest.approx(0.5)
    # 날짜 무효 + 체크섬 불일치 + 단서 없음 / 단서 없는 13자리 연속 숫자(바코드·일련번호): 잡지 않는다
    assert not hits("메모 321326-4930012", Kind.RRN)
    assert not hits("바코드 4006381333931", Kind.RRN)
    # (참고) 날짜 무효 + 체크섬 통과 + 하이픈만(단서 없음)은 위 0.6 단계다
    assert one("321326-4930011 이거 뭐야", Kind.RRN)[1] == pytest.approx(0.6)


def test_rrn_partially_masked_and_split_forms():
    got, score = one("주민번호 900101-123456*", Kind.RRN)
    assert got == "900101-123456*" and score >= 0.7
    got, score = one("주민등록번호 앞자리 900101 뒷자리 1234567", Kind.RRN)
    assert got == "900101 뒷자리 1234567" and score >= 0.7
    # 거의 다 가린 번호(900101-1******)는 정보가 거의 없어 잡지 않는다
    assert not hits("주민번호 900101-1******", Kind.RRN)


def test_rrn_existing_behavior_unchanged():
    assert one("주민번호 900101-1234568", Kind.RRN)[1] in (0.97, 0.6)  # 날짜 유효: 기존 단계 유지


# ---------- CARD ----------
@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("카드 사진에서 읽은 번호 3566-002O-2O36-0SO5", "3566-002O-2O36-0SO5"),
        ("카드 사진에서 읽은 번호 55SS-5555-555S-4444", "55SS-5555-555S-4444"),
        ("카드번호 3 5 6 6 0 0 2 0 2 0 3 6 0 5 0 5 결제해줘", "3 5 6 6 0 0 2 0 2 0 3 6 0 5 0 5"),
        ("결제 카드 4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 로 해줘", "4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1"),
        ("결제 카드 35660020 20360505 로 해줘", "35660020 20360505"),
        ("결제 카드 5105 10510510 5100 로 해줘", "5105 10510510 5100"),
        ("결제 카드 4000 - 0000 - 0000 - 0002 로 해줘", "4000 - 0000 - 0000 - 0002"),
    ],
)
def test_card_unusual_forms_detected_and_blocked(text, value):
    got, score = one(text, Kind.CARD)
    assert got == value and score >= 0.7


def test_card_loose_grouping_without_context_is_mask_only():
    got, score = one("35660020 20360505", Kind.CARD)
    assert got == "35660020 20360505" and 0.5 <= score < 0.7


@pytest.mark.parametrize(
    "text",
    [
        "2026 11 03 2026 11 03",  # 날짜 나열
        "전화 010 1234 5678 문의",
        "주문번호 35660020 20360505",  # 주문번호 문맥(느슨한 묶음은 버린다)
        "3566 0020 2036",  # 12자리
        "ISO 27001 SOS 도움 요청",  # 알파벳 단어
    ],
)
def test_card_negatives(text):
    assert not hits(text, Kind.CARD)


# ---------- SECRET ----------
@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("비밀번호: 공동현관 1234 세대 5678", "1234"),
        ("인증번호 왔어? 482913", "482913"),
        ("비번은 생일 뒤집은 거 1010", "1010"),
        ("OTP 방금 받은 거 임시로 930214 야", "930214"),
    ],
)
def test_secret_cue_window_detected_and_blocked(text, value):
    got, score = one(text, Kind.SECRET)
    assert got == value and score >= 0.7


def test_secret_year_like_value_is_mask_only():
    got, score = one("비밀번호 바꿨어, 2026", Kind.SECRET)
    assert got == "2026" and score < 0.7


@pytest.mark.parametrize(
    "text",
    [
        "엄마 생일 1010",  # 단서 없는 4자리 숫자는 비밀번호로 단정하지 않는다
        "비번 2024년",
        "인증번호 6자리 입력해",
        "비밀번호 90일마다 변경해야 해",
        "인증번호 문자 받으면 010-1234-5678 로 알려줘",
        "OTP 3분 이내 5000원 결제",
        "비밀번호 확인 12:30 에 만나",
    ],
)
def test_secret_negatives(text):
    assert not hits(text, Kind.SECRET)


# ---------- 위치 매핑·정책 일치·기존 우선순위 ----------
def test_spans_map_back_to_original_text_and_do_not_overlap():
    text = (
        "계좌번호 구삼칠 칠칠칠 사사칠일이팔 로 보내줘 / 카드번호 3 5 6 6 0 0 2 0 2 0 3 6 0 5 0 5"
    )
    spans = detect(text)
    assert [text[s.start : s.end] for s in spans] == [
        "구삼칠 칠칠칠 사사칠일이팔",
        "3 5 6 6 0 0 2 0 2 0 3 6 0 5 0 5",
    ]
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:], strict=False))


def test_score_and_policy_agree_block_vs_mask():
    with Pseudonymizer() as pz:
        blocked = pz.apply("주민등록번호는 321326-4930011 입니다", ANALYSIS)
        assert blocked.blocked and "321326" not in blocked.text  # 0.75 → 메시지 차단
        masked = pz.apply("본인확인 300332-4560920 다시 해줘", ANALYSIS)
        assert (
            not masked.blocked and "300332" not in masked.text and "[" in masked.text
        )  # 0.6 → 값만 가림
        weak = pz.apply("110-123-456789 로 보내줘", ANALYSIS)
        assert not weak.blocked and "456789" not in weak.text  # 0.6 → 값만 가림


def test_existing_priority_high_risk_beats_phone():
    # 전화번호 모양이 있어도 계좌 단서가 있는 12자리 묶음은 계좌, 순수 전화번호는 그대로 전화
    assert hits("전화 010-1234-5678", Kind.PHONE) and not hits("전화 010-1234-5678", Kind.ACCOUNT)
    assert not hits("계좌 010-1234-5678", Kind.ACCOUNT)


def test_ordinary_text_untouched():
    for text in [
        "일이삼사오육칠팔구십 외우기",
        "오늘 저녁은 구이구이 이야기",
        "ISO 27001 인증 SOS 신호",
        "회의는 3월 5일 오후 3시 2026-11-03",
    ]:
        assert not [
            s for s in detect(text) if s.kind in (Kind.ACCOUNT, Kind.RRN, Kind.CARD, Kind.SECRET)
        ], text
