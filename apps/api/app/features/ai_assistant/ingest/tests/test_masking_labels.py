"""라벨이 붙은 번호·이름·주소·계좌 가리기(2026-10-26 보강). 줄 모양은 실제 OCR 결과에서 가져왔다."""

import pytest

from app.features.ai_assistant.ingest.masking import mask_text


@pytest.mark.parametrize(
    ("line", "hidden", "kept"),
    [
        ("고객번호3456-7890-12", "3456-7890-12", "고객번호"),
        ("고객번호: 100234567", "100234567", "고객번호"),
        ("보험증권번호 LF-2026-004455", "LF-2026-004455", "보험증권번호"),
        ("가입자 홍길동 증권번호LF-2026-004455", "LF-2026-004455", "가입자"),
        ("회원번호 M20261234", "M20261234", "회원번호"),
        ("환자명 홍길동 등록번호20261008-0123", "20261008-0123", "등록번호"),
        ("계약번호 2026-L-00991", "2026-L-00991", "계약번호"),
    ],
)
def test_labeled_numbers_are_masked(line, hidden, kept):
    out = mask_text(line)
    assert hidden not in out
    assert kept in out  # 라벨은 남겨 무슨 값이었는지 알 수 있게 한다


@pytest.mark.parametrize(
    "line",
    [
        "사업자등록번호 123-45-67890",  # 사업자 번호는 개인이 아니라 가게의 것
        "승인번호 12345678",
        "주문번호 2026102600123",
    ],
)
def test_numbers_that_do_not_identify_a_person_stay(line):
    assert mask_text(line) == line


def test_resident_registration_label_keeps_its_own_rule():
    assert mask_text("주민등록번호 900101-1234567") == "주민등록번호 ******-*******"


@pytest.mark.parametrize(
    ("line", "hidden"),
    [
        ("가입자: 홍길동 / 피보험자 김영희", ("홍길동", "김영희")),
        ("계약자 박서준 (본인)", ("박서준",)),
        ("수령인 이몽룡 연락처 010-1234-5678", ("이몽룡", "1234-5678")),
        ("납부자 최민수", ("최민수",)),
    ],
)
def test_more_name_labels(line, hidden):
    out = mask_text(line)
    for h in hidden:
        assert h not in out


def test_chained_labels_hide_the_real_name():
    # "성명"을 이름으로 보고 "성*"로 가린 뒤 진짜 이름이 남던 버그
    out = mask_text("환자 성명 김영희", "prescription")
    assert "김영희" not in out
    assert "김**" in out
    assert "성명" in out


def test_bank_name_between_label_and_account():
    assert "987-654-321098" not in mask_text("납부계좌 가나은행987-654-321098")
    assert "110-123-456789" not in mask_text("입금계좌 신한은행 110-123-456789")


@pytest.mark.parametrize(
    "line",
    [
        "성명박서준 사용 주소 서울특별시 강동구 천호대로1000,101동 502호",
        "배송지 주소: 서울특별시 마포구 월드컵북로 396",
    ],
)
def test_address_label_in_the_middle_of_a_line(line):
    out = mask_text(line)
    assert "서울특별시" not in out
    assert "[주소 가림]" in out


def test_residence_without_label_needs_building_and_unit():
    assert mask_text("서울 강동구 천호대로 1000, 101동 502호") == "[주소 가림]"
    assert "[주소 가림]" in mask_text(
        "제1조(목적물) 서울특별시 강동구 천호대로 1000, 101동 502호, 전용 59㎡."
    )
    # 동·호가 없는 주소(가게 위치 등)는 라벨이 없으면 그대로 둔다
    shop = "하나로마트 서울 강남구 테헤란로 123 1층"
    assert mask_text(shop) == shop


def test_address_book_word_is_not_an_address_label():
    assert mask_text("주소록 백업") == "주소록 백업"
