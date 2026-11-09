"""개인정보 가리기. 원본은 원본 데이터 센터(raw_store)에만 두고, DB·검색에는 이 결과를 쓴다.

    모든 문서      주민·외국인등록번호만 (어디에 나오든)
    처방전         + 카드·전화·이메일·계좌·이름, 질병분류기호(병명 코드), 의사 면허번호, 주소
    신분증         + 카드·전화·이메일·계좌·이름, 라벨 없는 이름 줄, 운전면허·여권 번호, 주소
    통장           + 카드·전화·이메일·이름, 라벨 없는 계좌번호·이름 줄, 주소
    가족관계증명서  + 가족 이름(구분 칸 옆), 출생연월일, 등록기준지, 이름 줄
    그 밖(영수증·가정통신문·엑셀 …)  + 카드·전화·이메일·계좌 번호, 라벨 있는 이름·주소(외부 모델로 나가므로 확대)
    모든 문서(2026-10-26 보강)      + 라벨 있는 번호(고객·증권·계약·가입자·회원·환자·등록 번호), 은행 이름이 낀 계좌,
                                     줄 중간 라벨의 주소, 동·호까지 있는 주거지 주소. 승인·주문·사업자등록 번호는 그대로 둔다

처방전의 약 이름·용법·투약일수는 복약 챙기기에 필요해서 남긴다. 금액·날짜는 가리지 않는다.
"""

import re
from collections import Counter
from typing import Literal

from app.shared.privacy.detectors import detect as _detect_spans
from app.shared.privacy.types import Kind

Sensitive = Literal["none", "prescription", "id_card", "bankbook", "family_cert"]

# 구분은 하이픈·점·긴 대시·공백 모두, 구분 없는 13자리는 생년월일 모양(월 01~12, 일 01~31)일 때만
_RRN = re.compile(
    r"(?<!\d)\d{6}[ \t]*[-.·‐-―][ \t]*[1-8][\d*]{6}(?![\d*])"
    r"|(?<![\d*])\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[ \t]*[1-8]\d{6}(?!\d)"
)
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
# 라벨 뒤는 형태와 상관없이 가린다: OCR 이 숫자를 x 로 잘못 읽거나("5x0101-2****") 일부만 가려진 경우
_RRN_LABEL = re.compile(
    r"((?:주민\s*(?:등록)?\s*번호|외국인\s*등록\s*번호)[ \t]*[:：]?[ \t]*)([0-9A-Za-z*][0-9A-Za-z* \t-]{4,15}[0-9A-Za-z*])"
)
_CARD = re.compile(r"(?<!\d)(\d{4})[- ]?[\d*]{4}[- ]?[\d*]{4}[- ]?([\d*]{3,4})(?![\d*])")
_PHONE = re.compile(r"(?<!\d)(0\d{1,2})[-) .]?\d{3,4}[- .]?\d{4}(?!\d)")
_EMAIL = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
# 라벨과 숫자 사이에 은행 이름이 끼어도("납부계좌 가나은행987-654-321098") 가린다
_ACCOUNT = re.compile(
    r"((?:계좌|입금|예금)\s*(?:번호)?\s*[:：]?\s*(?:[가-힣A-Za-z]{2,8}(?:은행|뱅크|농협|신협|새마을금고|우체국)\s*)?)(\d[\d -]{7,}\d)"
)
_NAME_LABELS = (
    r"성\s*명|이\s*름|환\s*자(?:\s*명)?|수\s*진\s*자|고\s*객\s*명|예\s*금\s*주|수\s*신\s*인|수\s*검\s*자|수\s*강\s*생|학\s*생\s*명|보\s*호\s*자|"
    r"신\s*청\s*인|신\s*청\s*자|임\s*차\s*인|임\s*대\s*인|원\s*장|대\s*표\s*자|"
    r"가\s*입\s*자|피\s*보\s*험\s*자|계\s*약\s*자|수\s*익\s*자|납\s*부\s*자|청\s*구\s*인|세\s*대\s*주|"
    r"예\s*약\s*자|투\s*숙\s*객|탑\s*승\s*자|주\s*문\s*자|수\s*령\s*인|수\s*취\s*인"
)
# 라벨이 이어져도("환자 성명 김영희") 마지막 라벨 뒤의 값을 이름으로 본다
_NAME = re.compile(r"((?:(?:" + _NAME_LABELS + r")[ \t]*[:：]?[ \t]*)+)([가-힣]{2,4})")
# 처방전·신분증처럼 표 모양 문서는 라벨 칸과 값 칸이 줄로 나뉘어 읽히므로 다음 줄의 이름까지 가린다
_NAME_MULTILINE = re.compile(r"((?:(?:" + _NAME_LABELS + r")\s*[:：]?\s*)+)([가-힣]{2,4})")
# 라벨이 붙은 번호(고객·증권·계약·환자·등록 번호 …). 주민·외국인·사업자 등록번호는 다른 규칙이라 뺀다.
# 승인번호·주문번호처럼 개인을 가리키지 않는 번호는 가리지 않는다
_LABELED_NO = re.compile(
    r"((?<!주민)(?<!외국인)(?<!사업자)(?:고\s*객|증\s*권|보험\s*증권|계\s*약|가\s*입\s*자?|회\s*원|환\s*자|등\s*록|수\s*용\s*가|납\s*부\s*자)"
    r"\s*번\s*호[ \t]*[:：]?[ \t]*)([A-Za-z0-9][A-Za-z0-9*-]{4,}[A-Za-z0-9*])"
)
_REGIONS = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주"
# 줄 중간에 라벨이 있는 주소("성명 … 사용 주소 서울특별시 …"). 가게 주소도 라벨이 있으면 가려진다
_ADDRESS_INLINE = re.compile(r"(주\s*소(?!록)(?:지)?\s*[:：]?\s*)((?:" + _REGIONS + r")[^\n]*)")
# 라벨 없는 주거지 주소: 도로명에 동·호 번호까지 있는 것만(동·호가 없는 가게 주소는 남긴다)
_RESIDENCE = re.compile(
    r"(?:(?:"
    + _REGIONS
    + r")[가-힣]*\s+)?[가-힣]+(?:시|군|구)\s+[가-힣0-9]+(?:로|길)\s*\d[\d-]*(?:\s*,\s*|\s+)?\d+\s*동\s*\d+\s*호"
)
# 처방전 전용
_DISEASE = re.compile(
    r"((?:질병\s*분류\s*기호|상병\s*코드|진단\s*코드)\s*[:：]?\s*)([A-Z]\d{2}(?:\.\d{1,2})?(?:\s*[,/]\s*[A-Z]\d{2}(?:\.\d{1,2})?)*)"
)
_LICENSE = re.compile(r"(면허\s*번호\s*[:：]?\s*제?\s*)(\d+)")
_ADDRESS = re.compile(r"((?:^|\n)\s*주\s*소(?!록)\s*[:：]?\s*)([^\n]+)")
_PRESCRIPTION_WORDS = (
    "처방전",
    "처방의약품",
    "투약일수",
    "질병분류기호",
    "조제",
    "복용",
    "1일투여",
    "용법",
)
# 신분증 전용: 신분증에는 이름·주소에 라벨이 없다
_ID_WORDS = (
    "주민등록증",
    "외국인등록증",
    "운전면허증",
    "장애인등록증",
    "여권",
    "PASSPORT",
    "국가유공자증",
)
_ID_PROOF = re.compile(r"발급|청장|경찰청|시장|군수|구청|Date of issue|Passport No", re.IGNORECASE)
_DRIVER = re.compile(r"(?<!\d)\d{2}[- ]?\d{2}[- ]?\d{6}[- ]?\d{2}(?!\d)")
_PASSPORT = re.compile(r"\b[MSRGDT]\d{8}\b|\b[MSRGDT]\d{3}[A-Z]\d{4}\b")
# 여권의 영문 이름 줄(대문자 낱말 2~3개만 있는 줄). "REPUBLIC OF KOREA" 같은 줄도 가려지지만 해가 없다
_EN_NAME_LINE = re.compile(r"(?m)^([ \t]*)([A-Z]{2,}(?:[ ,]+[A-Z]{2,}){1,2})([ \t]*)$")
_NAME_LINE = re.compile(r"(?m)^([ \t]*)([가-힣]{2,4})([ \t]*(?:\([一-龥]{2,4}\))?[ \t]*)$")
_ADDRESS_LINE = re.compile(
    r"(?m)^([ \t]*)((?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|"
    r"경상|경북|경남|제주)[^\n]*)$"
)
# 통장 전용: 통장 사본에는 계좌번호에 라벨이 없는 경우가 많다
_BANKBOOK_WORDS = ("통장", "예금주", "보통예금", "입출금", "저축예금", "예금거래")
_BANKS = re.compile(
    r"국민|신한|우리|하나|농협|NH|기업은행|IBK|카카오뱅크|토스뱅크|케이뱅크|새마을금고|신협|우체국|"
    r"SC제일|씨티|수협|부산은행|대구은행|iM뱅크|경남은행|광주은행|전북은행|제주은행|산업은행"
)
# 숫자 묶음 2~4개(하이픈) 또는 숫자 10~14자리. 날짜(8자리)는 자리 수로 걸러낸다
_ACCOUNT_NUM = re.compile(r"(?<![\d-])(?:\d{2,6}-){1,3}\d{2,8}(?![\d-])|(?<!\d)\d{10,14}(?!\d)")


# 가족관계증명서 전용: 표 안의 이름은 라벨 대신 구분(본인·부·모 …) 옆에 있다
_FAMILY_WORDS = ("가족관계증명서", "가족관계등록부", "가족관계증명")
_RELATION_NAME = re.compile(
    r"((?:본인|부|모|배우자|자녀|자|녀)[ \t]*\|?[ \t]*)([가-힣]{2,4})(?=[ \t]*(?:\||\(|\n|$|\d))"
)
_BIRTH = re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일")
_REG_BASE = re.compile(r"(등록\s*기준지\s*[:：|]?\s*)([^\n|]+)")


def _account_repl(m: re.Match) -> str:
    digits = sum(c.isdigit() for c in m.group(0))
    return re.sub(r"\d", "*", m.group(0)) if 10 <= digits <= 16 else m.group(0)


def _mask_phone_variants(text: str) -> str:
    """정규식이 못 잡는 전화번호 꼴(한글 숫자, 82 붙임, 010 없는 8자리 …)은 공용 탐지기가 찾은 구간을 가린다."""
    spans = [s for s in _detect_spans(text) if s.kind == Kind.PHONE]
    for s in reversed(spans):  # 뒤에서부터 바꿔야 앞 구간의 위치가 안 밀린다
        text = text[: s.start] + "[연락처 가림]" + text[s.end :]
    return text


def _mask_home_units(text: str) -> str:
    """공용 탐지기가 찾은 주소 중 호수가 붙은 것(집 주소 꼴)만 가린다. 호수 없는 가게 주소는 남긴다."""
    spans = [
        s
        for s in _detect_spans(text)
        if s.kind == Kind.ADDRESS and re.search(r"\d\s?호", text[s.start : s.end])
    ]
    for s in reversed(spans):
        text = text[: s.start] + "[주소 가림]" + text[s.end :]
    return text


def is_prescription(text: str) -> bool:
    """처방전 낱말이 두 가지 이상 보이면 처방전으로 본다(자동 분류 전 단계의 보수적 판단)."""
    flat = re.sub(r"\s+", "", text)
    return sum(w in flat for w in _PRESCRIPTION_WORDS) >= 2


def is_id_card(text: str) -> bool:
    """신분증 이름(주민등록증·운전면허증·여권 …)이 보이고, 주민번호·면허번호·발급 기관 같은 증거가 하나 더 있으면."""
    flat = re.sub(r"\s+", "", text)
    if not any(w.lower() in flat.lower() for w in _ID_WORDS):
        return False
    return bool(
        _RRN.search(text)
        or _RRN_LABEL.search(text)
        or _DRIVER.search(text)
        or _PASSPORT.search(text)
        or _ID_PROOF.search(text)
    )


def is_bankbook(text: str) -> bool:
    """통장 낱말(통장·예금주 …)이 보이고, 은행 이름이나 계좌번호 꼴이 하나 더 있으면."""
    flat = re.sub(r"\s+", "", text)
    if not any(w in flat for w in _BANKBOOK_WORDS):
        return False
    return bool(
        _BANKS.search(text)
        or any(_account_repl(m) != m.group(0) for m in _ACCOUNT_NUM.finditer(text))
    )


# 개인 금융 문서의 낱말: 통장 사본·이체확인증·거래내역은 받는 사람 이름·금액·잔액이 함께 있다
_NOT_NOTICE_WORDS = (
    "통장",
    "보통예금",
    "저축예금",
    "예금거래",
    "입출금",
    "이체확인",
    "이체내역",
    "송금확인",
    "거래내역",
    "거래명세",
    "잔액",
    "받는분",
    "받는사람",
    "보낸분",
    "보내는분",
    "출금계좌",
    "입금계좌",
)
# 납부·학교 안내의 낱말: 계좌를 알리는 안내문이라는 증거
_NOTICE_WORDS = (
    "납부",
    "납입",
    "수납",
    "회비",
    "가정통신",
    "학부모",
    "학교",
    "유치원",
    "어린이집",
    "학원",
)


def is_account_notice(text: str) -> bool:
    """통장류(`bankbook`)로 잡힌 글이 학교·기관의 납부 계좌 안내문인가. **가리기 전의 글**로 판단한다
    (가린 뒤에는 줄 하나에 혼자 있는 "통장"이 이름처럼 `통***` 로 가려져 낱말이 사라진다).
    통장·이체확인증·거래내역 같은 개인 금융 낱말이 하나도 없고, 납부·학교 같은 안내 낱말이 있어야 한다."""
    flat = re.sub(r"\s+", "", text)
    if any(w in flat for w in _NOT_NOTICE_WORDS):
        return False
    return any(w in flat for w in _NOTICE_WORDS)


def is_family_cert(text: str) -> bool:
    """증명서 이름이 보이고, 증명서에만 있는 칸(등록기준지, 출생연월일+주민등록번호)이 하나 더 있으면.
    제출 서류 안내처럼 이름만 언급한 문서는 증명서로 보지 않는다(짧은 낱말이 이름으로 잘못 가려진다)."""
    flat = re.sub(r"\s+", "", text)
    if not any(w in flat for w in _FAMILY_WORDS):
        return False
    return "등록기준지" in flat or (
        "주민등록번호" in flat and ("출생연월일" in flat or "성명" in flat)
    )


def sensitive_kind(text: str) -> Sensitive:
    if is_prescription(text):
        return "prescription"
    if is_family_cert(text):  # 신분증보다 먼저: 증명서에도 '주민등록번호'·'발급'이 나온다
        return "family_cert"
    if is_id_card(text):
        return "id_card"
    if is_bankbook(text):
        return "bankbook"
    return "none"


def mask_text(text: str, kind: Sensitive = "none", *, counts: Counter | None = None) -> str:
    """kind 가 none 이면 주민·외국인등록번호만, 처방전·신분증·통장이면 개인정보를 모두 가린다."""
    counts = Counter() if counts is None else counts
    text = text.translate(_FULLWIDTH_DIGITS)

    def sub(name: str, pattern: re.Pattern, repl) -> None:
        nonlocal text
        text, n = pattern.subn(repl, text)
        counts[name] += n

    # 라벨 쪽을 먼저: 가린 결과(******-*******)는 숫자가 없어 아래 패턴에 다시 걸리지 않는다
    sub("rrn", _RRN_LABEL, lambda m: m.group(1) + "******-*******")
    sub("rrn", _RRN, "******-*******")
    if (
        kind == "none"
    ):  # 일반 문서도 연락처·카드·계좌·이메일·라벨 있는 이름·주소는 가린다(외부 모델로 나가므로)
        sub("card", _CARD, lambda m: f"{m.group(1)}-****-****-{m.group(2)[-4:]}")
        sub("phone", _PHONE, lambda m: f"{m.group(1)}-****-****")
        text = _mask_phone_variants(text)
        sub("email", _EMAIL, lambda m: f"{m.group(1)}***@{m.group(2)}")
        sub("account", _ACCOUNT, lambda m: m.group(1) + re.sub(r"\d", "*", m.group(2)))
        sub("name", _NAME, lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1))
        sub("number", _LABELED_NO, lambda m: m.group(1) + re.sub(r"[A-Za-z0-9]", "*", m.group(2)))
        sub("address", _ADDRESS, lambda m: m.group(1) + "[주소 가림]")
        sub("address", _ADDRESS_INLINE, lambda m: m.group(1) + "[주소 가림]")
        sub("address", _RESIDENCE, "[주소 가림]")
        text = _mask_home_units(text)
        return text
    if kind == "id_card":  # 카드번호 패턴보다 먼저: 면허번호(12자리)가 카드번호로 잘못 걸리지 않게
        sub("license", _DRIVER, "**-**-******-**")
        sub("passport", _PASSPORT, "*********")
        sub("name", _EN_NAME_LINE, lambda m: m.group(1) + m.group(2)[0] + "***" + m.group(3))
    if kind == "family_cert":
        sub(
            "name",
            _RELATION_NAME,
            lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1),
        )
        sub("birth", _BIRTH, "****년 **월 **일")
        sub("address", _REG_BASE, lambda m: m.group(1) + "[등록기준지 가림]")
    if kind == "bankbook":  # 카드번호 패턴보다 먼저: 16자리 계좌번호도 통째로 가린다
        sub("phone", _PHONE, lambda m: f"{m.group(1)}-****-****")
        counts["account"] += sum(
            _account_repl(m) != m.group(0) for m in _ACCOUNT_NUM.finditer(text)
        )
        text = _ACCOUNT_NUM.sub(_account_repl, text)
    sub("card", _CARD, lambda m: f"{m.group(1)}-****-****-{m.group(2)[-4:]}")
    sub("phone", _PHONE, lambda m: f"{m.group(1)}-****-****")
    text = _mask_phone_variants(text)
    sub("email", _EMAIL, lambda m: f"{m.group(1)}***@{m.group(2)}")
    sub("account", _ACCOUNT, lambda m: m.group(1) + re.sub(r"\d", "*", m.group(2)))
    sub(
        "name",
        _NAME_MULTILINE,
        lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1),
    )
    sub("number", _LABELED_NO, lambda m: m.group(1) + re.sub(r"[A-Za-z0-9]", "*", m.group(2)))
    sub("address", _ADDRESS, lambda m: m.group(1) + "[주소 가림]")
    sub("address", _ADDRESS_INLINE, lambda m: m.group(1) + "[주소 가림]")
    sub("address", _RESIDENCE, "[주소 가림]")
    text = _mask_home_units(text)
    if kind == "prescription":
        sub("disease_code", _DISEASE, lambda m: m.group(1) + "[병명 코드 가림]")
        sub("license", _LICENSE, lambda m: m.group(1) + "*" * len(m.group(2)))
    else:
        sub("address", _ADDRESS_LINE, lambda m: m.group(1) + "[주소 가림]")
        sub("name", _NAME_LINE, lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1))
    return text
