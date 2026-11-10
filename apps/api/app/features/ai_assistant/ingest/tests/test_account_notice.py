"""학교·기관의 납부 계좌 안내문과 개인 금융 문서(통장 사본·이체확인증·거래내역)를 가린다: 통장류(bankbook)로 잡힌 글 중 안내문만 일반 문서로 본다.
판단은 가리기 전의 글로 한다(가린 뒤에는 줄 하나에 혼자 있는 "통장"이 이름처럼 가려져 낱말이 사라진다)."""

from app.features.ai_assistant.ingest import masking

FEE_NOTICE = """해솔초등학교 과회비 납부 안내문
과회비 200,000원 이십만원을 납부해 주세요
방법 우리은행 1002-123-456789 예금주 해솔초등학교
계좌이체 시 학생 본인 이름으로 입금해 주세요"""

PASSBOOK_TITLE_ALONE = """KB국민은행
통장사본
예금주 김가비
계좌번호 123456-12-345678
신규일 2024년 3월 2일"""

TRANSFER_PROOF = """이체확인증
출금계좌 국민은행 123456-12-345678 예금주 김가비
입금계좌 우리은행 1002-345-678901
받는분 이철수
이체금액 1,500,000원 메모 3월 월세"""

TRANSACTION_LIST = """입출금 거래내역 조회
우리은행 1002-123-456789 예금주 김가비
2026.11.01 이철수 입금 300,000
2026.11.03 관리비 출금 120,000
잔액 2,345,000원"""


def test_a_school_fee_notice_is_a_bankbook_that_is_an_account_notice():
    assert masking.sensitive_kind(FEE_NOTICE) == "bankbook"
    assert masking.is_account_notice(FEE_NOTICE) is True


def test_a_passbook_whose_title_stands_alone_is_not_an_account_notice():
    assert masking.sensitive_kind(PASSBOOK_TITLE_ALONE) == "bankbook"
    assert (
        masking.is_account_notice(PASSBOOK_TITLE_ALONE) is False
    )  # "통장사본" 한 줄도 통장 낱말이다


def test_transfer_proofs_and_transaction_lists_are_not_account_notices():
    for text in (TRANSFER_PROOF, TRANSACTION_LIST):
        assert masking.sensitive_kind(text) == "bankbook"
        assert (
            masking.is_account_notice(text) is False
        )  # 받는 사람 이름·금액·잔액이 든 개인 금융 문서


def test_a_notice_needs_payment_or_school_evidence():
    only_an_account = "우리은행 1002-123-456789 예금주 김가비"
    assert masking.is_account_notice(only_an_account) is False  # 안내문이라는 증거가 없다


def test_spacing_does_not_hide_the_passbook_word():
    assert masking.is_account_notice("저축 통 장 사본 예금주 김가비 납부") is False
