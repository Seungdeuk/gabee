"""개인정보 가리기. 원본은 원본 데이터 센터(raw_store)에만 두고, DB·검색에는 이 결과를 쓴다.

    모든 문서      주민·외국인등록번호만 (어디에 나오든)
    처방전         + 카드·전화·이메일·계좌·이름, 질병분류기호(병명 코드), 의사 면허번호, 주소
    신분증         + 카드·전화·이메일·계좌·이름, 라벨 없는 이름 줄, 운전면허·여권 번호, 주소
    통장           + 카드·전화·이메일·이름, 라벨 없는 계좌번호·이름 줄, 주소
    가족관계증명서  + 가족 이름(구분 칸 옆), 출생연월일, 등록기준지, 이름 줄
    그 밖(영수증·가정통신문·엑셀 …)  + 카드·전화·이메일·계좌 번호, 라벨 있는 이름·주소(외부 모델로 나가므로 확대)

처방전의 약 이름·용법·투약일수는 복약 챙기기에 필요해서 남긴다. 금액·날짜는 가리지 않는다.
"""

import re
from collections import Counter
from typing import Literal

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
_ACCOUNT = re.compile(r"((?:계좌|입금|예금)\s*(?:번호)?\s*[:：]?\s*)(\d[\d -]{7,}\d)")
_NAME = re.compile(
    r"((?:성\s*명|이\s*름|환\s*자(?:\s*명)?|수\s*진\s*자|고\s*객\s*명|예\s*금\s*주|수\s*신\s*인|수\s*검\s*자|수\s*강\s*생|학\s*생\s*명|보\s*호\s*자|신\s*청\s*인|신\s*청\s*자|임\s*차\s*인|임\s*대\s*인|원\s*장|대\s*표\s*자)\s*[:：]?\s*)([가-힣]{2,4})"
)
# 처방전 전용
_DISEASE = re.compile(
    r"((?:질병\s*분류\s*기호|상병\s*코드|진단\s*코드)\s*[:：]?\s*)([A-Z]\d{2}(?:\.\d{1,2})?(?:\s*[,/]\s*[A-Z]\d{2}(?:\.\d{1,2})?)*)"
)
_LICENSE = re.compile(r"(면허\s*번호\s*[:：]?\s*제?\s*)(\d+)")
_ADDRESS = re.compile(r"((?:^|\n)\s*주\s*소\s*[:：]?\s*)([^\n]+)")
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
        sub("email", _EMAIL, lambda m: f"{m.group(1)}***@{m.group(2)}")
        sub("account", _ACCOUNT, lambda m: m.group(1) + re.sub(r"\d", "*", m.group(2)))
        sub("name", _NAME, lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1))
        sub("address", _ADDRESS, lambda m: m.group(1) + "[주소 가림]")
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
    sub("email", _EMAIL, lambda m: f"{m.group(1)}***@{m.group(2)}")
    sub("account", _ACCOUNT, lambda m: m.group(1) + re.sub(r"\d", "*", m.group(2)))
    sub("name", _NAME, lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1))
    sub("address", _ADDRESS, lambda m: m.group(1) + "[주소 가림]")
    if kind == "prescription":
        sub("disease_code", _DISEASE, lambda m: m.group(1) + "[병명 코드 가림]")
        sub("license", _LICENSE, lambda m: m.group(1) + "*" * len(m.group(2)))
    else:
        sub("address", _ADDRESS_LINE, lambda m: m.group(1) + "[주소 가림]")
        sub("name", _NAME_LINE, lambda m: m.group(1) + m.group(2)[0] + "*" * (len(m.group(2)) - 1))
    return text
