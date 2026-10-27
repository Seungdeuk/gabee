"""한국어 대화에서 개인정보를 찾는 탐지기(정규식 + 검증). 표준 라이브러리만 쓴다.

공개 함수는 ``detect(text, known_names=())`` 하나다. 종류별 탐지기가 후보(Span)를 모으고, 겹치면
``HIGH 위험 먼저 -> 더 긴 것 먼저 -> 점수 높은 것 먼저`` 순서로 하나만 남긴다.

한계(중요): 이 모듈은 **완전하지 않다**.
- 이름: 가족 구성원 이름 사전(known_names)에 있는 것만 높은 점수로 찾고, 그 밖에는 "성씨 + 이름 + 호칭(씨·님·군·양)"
  꼴만 낮은 점수로 찾는다. 호칭 없이 쓴 낯선 사람 이름, 별명, 외국 이름은 놓친다. 엄마·아빠 같은 가족 호칭은 이름이
  아니므로 마스킹하지 않는다.
- 주소: 도로명·지번·동호수와 '시/도 + 시/군/구'만 본다. 건물 이름, 문장 속 약식 표현("강남역 3번 출구 앞 빌라")은 놓친다.
- 숫자: 띄어쓰기·오탈자가 섞이거나 한글 숫자("공일공")로 쓴 전화번호는 놓친다. 반대로 주문번호가 우연히 규칙에 맞으면 오탐한다.
- 이 모듈(``detect``)은 규칙만 쓴다. 이름·주소 보강용 NER 은 ``ner.detect_with_ner`` 가 이 결과 위에 더한다(선택). 마스킹은 위험을 줄일 뿐 보호를 보장하지 않는다.
"""

import calendar
import re
from bisect import bisect_left

from .types import RISK_RANK, Kind, Span

# ---------------------------------------------------------------------------
# 공통 도구
# ---------------------------------------------------------------------------
_HANGUL = re.compile(r"[가-힣]")
# 폭 없는 공백·결합 방지·방향 제어 문자(soft hyphen, ZWSP/ZWNJ/ZWJ, LRM/RLM, bidi 제어 등): 사람 눈에는 안 보이지만 숫자 사이에 끼면 정규식 탐지를 피할 수 있다
_INVISIBLE_RANGES = (
    (0x00AD, 0x00AD),  # soft hyphen
    (0x034F, 0x034F),  # combining grapheme joiner
    (0x180E, 0x180E),  # mongolian vowel separator
    (0x200B, 0x200F),  # zero width space/non-joiner/joiner, LRM, RLM
    (0x202A, 0x202E),  # bidi embedding/override
    (0x2060, 0x2064),  # word joiner, invisible operators
    (0x2066, 0x2069),  # bidi isolate
    (0xFEFF, 0xFEFF),  # BOM / zero width no-break space
)
INVISIBLE_CHARS = frozenset(chr(c) for lo, hi in _INVISIBLE_RANGES for c in range(lo, hi + 1))
_INVISIBLE = re.compile(
    "[" + "".join(f"\\u{lo:04x}-\\u{hi:04x}" for lo, hi in _INVISIBLE_RANGES) + "]"
)
# 탐지는 전각 문자(０１０-１２３４, ［］, 전각 공백)와 여러 가지 대시(– — ‐ − )를 반각으로 바꾼 글자에서 한다.
# 글자 수가 그대로라 구간 위치는 원문과 같다.
_FOLD: dict[int, int] = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
_FOLD.update({0x3000: 0x20, 0x2010: 0x2D, 0x2011: 0x2D, 0x2013: 0x2D, 0x2014: 0x2D, 0x2212: 0x2D})
# 운송장·주문번호처럼 긴 숫자가 개인정보가 아닌 문맥을 알려 주는 말(숫자 바로 앞 14자·뒤 6자 안에서 찾는다)
_NOT_PII_CONTEXT = re.compile(
    r"운송장|송장|택배|주문|예약번호|승인번호|접수|오류\s?코드|에러\s?코드|배송|등기|조회번호|회원번호|관리번호|"
    r"일련번호|시리얼|사업자등록|전표|영수증|품번|재고|바코드"
)


def _is_hangul(ch: str) -> bool:
    return bool(_HANGUL.fullmatch(ch))


def _near_not_pii(text: str, start: int, end: int) -> bool:
    return bool(
        _NOT_PII_CONTEXT.search(text[max(0, start - 14) : start])
        or _NOT_PII_CONTEXT.search(text[end : end + 6])
    )


def _luhn_ok(digits: str) -> bool:
    """카드번호 Luhn 검증."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# 전화번호
# ---------------------------------------------------------------------------
# 앞이 숫자이거나 '숫자-', '숫자.' 이면 더 긴 숫자열(날짜·주문번호)의 일부로 보고 제외한다.
_NUM_START = r"(?<!\d)(?<!\d[-.])"
_SEP = r"(?: ?[-./)] ?| )?"
_PHONE_MOBILE = rf"01[016789]{_SEP}\d{{3,4}}{_SEP}\d{{4}}"
_PHONE_LAND = rf"\(?(?:02|0(?:3[1-3]|4[1-4]|5[1-5]|6[1-4]))\)?{_SEP}\d{{3,4}}{_SEP}\d{{4}}"
_PHONE_NET = rf"(?:070|080|050[2-7]?){_SEP}\d{{3,4}}{_SEP}\d{{4}}"
_PHONE_INTL = (
    rf"\+82{_SEP}(?:\(0\){_SEP})?(?:10|1[16-9]|2|[3-6][1-5]|70|80){_SEP}\d{{3,4}}{_SEP}\d{{4}}"
)
PHONE_RE = re.compile(
    rf"{_NUM_START}(?:{_PHONE_INTL}|{_PHONE_MOBILE}|{_PHONE_LAND}|{_PHONE_NET})(?!\d)"
)
# 전화번호 후보가 한 덩어리 전체인지 확인할 때(계좌 후보에서 전화번호를 빼는 데) 쓴다.
_PHONE_FULL = re.compile(rf"(?:{_PHONE_INTL}|{_PHONE_MOBILE}|{_PHONE_LAND}|{_PHONE_NET})")


def _detect_phone(text: str) -> list[Span]:
    spans = []
    for m in PHONE_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(set(digits)) < 3:  # 0000000000 같은 자리 채우기 값
            continue
        spans.append(
            Span(
                Kind.PHONE, m.start(), m.end(), 0.95 if "-" in raw or "+" in raw else 0.85, "phone"
            )
        )
    return spans


# ---------------------------------------------------------------------------
# 이메일
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"
)


def _detect_email(text: str) -> list[Span]:
    return [Span(Kind.EMAIL, m.start(), m.end(), 0.97, "email") for m in EMAIL_RE.finditer(text)]


# ---------------------------------------------------------------------------
# 주민등록번호 / 외국인등록번호
# ---------------------------------------------------------------------------
RRN_RE = re.compile(r"(?<!\d)(?<!\d-)(\d{2})(\d{2})(\d{2})(?: ?- ?| )?([1-8])(\d{6})(?!\d)")
_RRN_WEIGHTS = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)


def _rrn_date_ok(yy: int, mm: int, dd: int, gender: int) -> bool:
    century = 1900 if gender in (1, 2, 5, 6) else 2000
    if not 1 <= mm <= 12:
        return False
    return 1 <= dd <= calendar.monthrange(century + yy, mm)[1]


def _rrn_checksum_ok(digits: str) -> bool:
    total = sum(int(d) * w for d, w in zip(digits[:12], _RRN_WEIGHTS, strict=True))
    check = (11 - total % 11) % 10
    if int(digits[6]) in (5, 6, 7, 8):  # 외국인등록번호
        check = (check + 2) % 10
    return check == int(digits[12])


def _detect_rrn(text: str) -> list[Span]:
    """형식(생년월일이 실제 달력에 있고 구분 숫자가 1~8)이 맞으면 체크섬이 틀려도 잡는다.

    근거: 2020년 10월 이후 발급 번호는 뒷자리가 임의 숫자라 체크섬이 맞지 않을 수 있고, 한 글자 오타가 난 번호도
    여전히 민감하다. 놓치는 쪽(유출)이 더 위험하므로 안전 쪽으로 기울여 HIGH 로 잡되 score 만 낮춘다.
    하이픈이 있으면 오탐 가능성이 더 낮으므로 체크섬 불일치여도 0.6, 하이픈이 없으면 0.45 를 준다.
    """
    spans = []
    for m in RRN_RE.finditer(text):
        yy, mm, dd, gender = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if not _rrn_date_ok(yy, mm, dd, gender):
            continue
        digits = re.sub(r"\D", "", m.group(0))
        has_sep = bool(re.search(r"[- ]", m.group(0)))
        if not has_sep and _near_not_pii(text, m.start(), m.end()):
            continue  # '운송장 9001011234567' 같은 번호
        if _rrn_checksum_ok(digits):
            score = 0.97
        else:
            score = 0.6 if has_sep else 0.45
        spans.append(Span(Kind.RRN, m.start(), m.end(), score, "rrn"))
    return spans


# ---------------------------------------------------------------------------
# 카드번호
# ---------------------------------------------------------------------------
CARD_RE = re.compile(
    r"(?<!\d)(?<!\d[- ])(?:"
    r"\d{4}([- ])\d{4}\1\d{4}\1\d{1,4}(?:\1\d{1,3})?"  # 4-4-4-4 (13~19자리)
    r"|\d{4}([- ])\d{6}\2\d{5}"  # 4-6-5 (15자리, 아멕스형)
    r"|\d{13,19}"
    r")(?!\d)"
)


def _card_prefix_ok(digits: str) -> bool:
    """실제 카드 발급 번호 대역(3,4,5,6,9 로 시작 / 2221~2720)만 본다. 연도로 시작하는 주문번호(20…)를 줄인다."""
    if digits[0] in "3456" or digits[0] == "9":
        return True
    return digits[0] == "2" and 2221 <= int(digits[:4]) <= 2720


_CARD_CONTEXT = re.compile(
    r"카드|결제|cvc|cvv|유효\s?기간|신용|체크|visa|master|amex", re.IGNORECASE
)


def _detect_card(text: str) -> list[Span]:
    """카드번호를 단계로 판단한다. 길이 13~19 와 발급 대역은 모든 단계의 전제다.

    - Luhn 통과: 4자리씩 끊어 쓴 번호 0.95 / 끊지 않은 15·16자리는 '카드·결제' 같은 문맥이 있으면 0.95, 없으면 0.65
      (정책의 차단 임계값 0.7 미만이라 가리기만 한다) / 그 밖의 길이 0.4. 운송장·주문번호 문맥이면 끊지 않은 번호는 버린다.
    - Luhn 실패(오타 난 번호·시험용 번호): 15·16자리이고 운송장·주문번호 문맥이 없을 때만, 형식이나 문맥이 확실하면 가린다.
      4자리씩 끊어 쓴 번호 0.6 / 끊지 않은 번호는 '카드·결제' 문맥이 있을 때 0.5 / 문맥도 구분자도 없으면 버린다.
      점수는 모두 차단 임계값(0.7) 미만이라 값만 가리고 메시지는 보낸다(오탐이어도 대화가 통째로 빠지지 않는다).
    """
    spans = []
    for m in CARD_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if not 13 <= len(digits) <= 19 or not _card_prefix_ok(digits):
            continue
        separated = digits != raw
        if _luhn_ok(digits):
            if len(digits) not in (15, 16):
                score = 0.4
            elif separated:
                score = 0.95
            elif _near_not_pii(text, m.start(), m.end()):
                continue
            elif _CARD_CONTEXT.search(text[max(0, m.start() - 20) : m.end() + 20]):
                score = 0.95
            else:
                score = 0.65
        else:
            if len(digits) not in (15, 16) or _near_not_pii(text, m.start(), m.end()):
                continue
            if separated:
                score = 0.6
            elif _CARD_CONTEXT.search(text[max(0, m.start() - 20) : m.end() + 20]):
                score = 0.5
            else:
                continue  # 문맥도 구분자도 없는 Luhn 실패 숫자는 주문번호·운송장일 가능성이 크다
        spans.append(Span(Kind.CARD, m.start(), m.end(), score, "card"))
    return spans


# ---------------------------------------------------------------------------
# 계좌번호(의심)
# ---------------------------------------------------------------------------
# 은행 이름만으로는 문맥이 되지 않는다('국민 10명', '카카오택시', '우체국 택배'). 아래 중 하나일 때만 계좌 문맥으로 본다.
#  - '계좌'·'예금주' 단어가 숫자 앞뒤 20자 안에 있다(0.7)
#  - '은행 이름 + 은행/뱅크/금고/계좌/입금/송금/이체' 가 20자 안에 있거나, 은행 이름이 숫자 바로 앞뒤에 붙어 있다(0.8)
#  - '입금·송금·이체' 만 있다(0.6, 약한 문맥이라 정책이 차단하지 않고 가리기만 한다)
# 우리·하나·부산 같이 일반 단어와 겹치는 이름은 바로 앞뒤에 붙어 있을 때도 '은행'이 있어야 한다.
_BANK_PLAIN = (
    "국민|신한|농협|기업|우체국|새마을|수협|신협|씨티|SC제일|제일|IBK|KB|NH|토스|카카오|케이|"
    "카카오뱅크|토스뱅크|케이뱅크|카뱅|토뱅|케뱅"
)
_BANK_AMBIGUOUS = "우리|하나|부산|대구|광주|전북|경남|제주|산업"
_BANK_ALL = f"{_BANK_PLAIN}|{_BANK_AMBIGUOUS}"
_ACCT_WORD = re.compile(r"계좌|예금주")
_ACCT_BANK_WINDOW = re.compile(
    rf"(?:{_BANK_ALL})\s?(?:은행|뱅크|금고|계좌|입금|송금|이체|예금)|\(\s?(?:{_BANK_ALL})\s?\)"
)
_ACCT_BANK_BEFORE = re.compile(rf"(?:(?:{_BANK_PLAIN})(?:은행)?|(?:{_BANK_AMBIGUOUS})은행)\s?$")
_ACCT_BANK_AFTER = re.compile(rf"^\s?(?:(?:{_BANK_PLAIN})(?:은행)?|(?:{_BANK_AMBIGUOUS})은행)")
_ACCT_WEAK = re.compile(r"입금|송금|이체")
_ACCOUNT_RE = re.compile(r"(?<!\d)(?<!\d-)(?:\d{2,6}(?:-\d{2,8}){1,3}|\d{10,14})(?!\d)(?!-\d)")
_ACCOUNT_WINDOW = 20


def _account_context(before: str, after: str) -> float | None:
    """계좌 문맥이면 기본 점수, 아니면 None."""
    if _ACCT_BANK_BEFORE.search(before) or _ACCT_BANK_AFTER.search(after):
        return 0.8
    window = f"{before} {after}"
    if _ACCT_BANK_WINDOW.search(window):
        return 0.8
    if _ACCT_WORD.search(window):
        return 0.7
    if _ACCT_WEAK.search(window):
        return 0.6
    return None


def _detect_account(text: str) -> list[Span]:
    spans = []
    for m in _ACCOUNT_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if not 10 <= len(digits) <= 14:
            continue
        if _PHONE_FULL.fullmatch(m.group(0)):  # 전화번호 모양은 전화로 본다
            continue
        before = text[max(0, m.start() - _ACCOUNT_WINDOW) : m.start()]
        after = text[m.end() : m.end() + _ACCOUNT_WINDOW]
        base = _account_context(before, after)
        if base is None:  # 문맥 없는 긴 숫자는 계좌로 단정하지 않는다
            continue
        if _near_not_pii(text, m.start(), m.end()):  # '주문번호', '운송장' 이 붙은 숫자
            continue
        spans.append(
            Span(
                Kind.ACCOUNT,
                m.start(),
                m.end(),
                min(0.95, base + (0.1 if "-" in m.group(0) else 0)),
                "account",
            )
        )
    return spans


# ---------------------------------------------------------------------------
# 비밀 정보 표현(비밀번호·인증번호 …): 값 부분만 구간으로 잡는다
# ---------------------------------------------------------------------------
SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:비밀\s?번호|비번|패스워드|핀\s?번호|(?i:pin)\s?번호|인증\s?번호|인증\s?코드|보안\s?코드|(?i:password|passwd|pw|pin|otp|cvc|cvv))"
    r"(?![A-Za-z])"
    r"(?:\s*[:=：]\s*|\s*(?:은|는|이|가)\s*|\s+)?"
    r"[\"'“‘`]?"
    r"(?P<val>[A-Za-z0-9!@#$%^&*()_+\-=\[\]{};:,.<>/?~|\\]{4,})"
)
_SECRET_TRAIL = ".,;:)?"
_NOT_A_SECRET_AFTER = "년월일시분초원개명%"
# 비밀번호 값이 아니라 지시어·일반 단어인 경우('비번 wifi 랑 같아', 'password same')
_SECRET_WORD_STOP = frozenset(
    "wifi same this that what with home none null true false email mail kakao naver google "
    "yes there here also like want need your mine".split()
)


def _detect_secret(text: str) -> list[Span]:
    spans = []
    for m in SECRET_RE.finditer(text):
        start = m.start("val")
        value = m.group("val").rstrip(_SECRET_TRAIL)
        if len(value) < 4:
            continue
        end = start + len(value)
        if value.isdigit() and end < len(text) and text[end] in _NOT_A_SECRET_AFTER:
            continue  # '비번 2024년' 같은 날짜·수량
        if value.isalpha() and value.lower() in _SECRET_WORD_STOP:
            continue
        has_digit_or_symbol = any(not c.isalpha() for c in value)
        spans.append(Span(Kind.SECRET, start, end, 0.9 if has_digit_or_symbol else 0.6, "secret"))
    return spans


# ---------------------------------------------------------------------------
# 주소
# ---------------------------------------------------------------------------
_UNIT_AFTER = (
    r"(?!\s?(?:개|명|분|시|원|살|세|층|번째|번(?!지|길)|일|월|년|kg|km|cm|mm|%|회|대|마리|장|잔|병|"
    r"인분|시간|주|달|호선|퍼센트|코스|바퀴|정거장|단계|가(?![가-힣])))"
)
_ROAD_RE = re.compile(
    r"(?<![가-힣])((?P<name>[가-힣]{2,10}(?:대로|로|길)(?:\s?\d{1,3}번?길)?|[가-힣]{1,8}\d{1,3}번?길))"
    r"\s?(\d{1,4})(?:-(\d{1,4}))?(?!\d)" + _UNIT_AFTER
)
_ROAD_STOP_SUFFIX = (
    "그대로", "마음대로", "멋대로", "맘대로", "뜻대로", "생각대로", "계획대로", "예정대로", "순서대로",
    "원래대로", "약속대로", "말대로", "본대로", "들은대로", "하는대로", "으로",
)  # fmt: skip
_JIBUN_RE = re.compile(
    r"(?<![가-힣])(?P<name>[가-힣]{2,6}(?P<suffix>동|읍|면|리))\s?(\d{1,4}(?:-\d{1,4})?)(?P<bunji>번지)?(?!\d)"
    + _UNIT_AFTER
)
_JIBUN_STOP = {
    "운동", "이동", "행동", "활동", "자동", "수동", "감동", "변동", "출동", "난동", "폭동", "소동",
    "충동", "작동", "기동", "율동", "노동", "발동", "연동", "인동", "대동", "공동", "합동", "참동",
}  # fmt: skip
_DONGHO_RE = re.compile(r"(?<!\d)\d{1,4}동\s?\d{1,5}호(?!\d|선)")
_SIDO = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
_SIDO_RE = re.compile(
    rf"(?<![가-힣])(?:{_SIDO})(?:특별시|광역시|특별자치시|특별자치도|도|시)?\s?(?P<d1>[가-힣]{{2,4}}[시군구]|[중동서남북]구)(?:\s(?P<d2>[가-힣]{{2,4}}[구군]|[중동서남북]구))?"
)
_DISTRICT_STOP = frozenset({"대도시", "신도시", "소도시", "중소도시", "도시"})
_ADDR_GAP = re.compile(r"[\s,]{0,2}")


def _phone_at(text: str, pos: int) -> bool:
    """pos 에서 전화번호 한 덩어리가 시작하는가(주소 뒤 번호가 건물번호·지번이 아니라 전화번호인지 가린다)."""
    return _PHONE_FULL.match(text, pos) is not None


_REGION_BEFORE = re.compile(r"[가-힣]{1,4}[시군구][\s,]{0,2}$")


def _region_before(text: str, pos: int) -> bool:
    """pos 바로 앞(공백·쉼표 두 칸 안)이 '서울시'·'강남구'·'수원시' 같은 시·군·구 이름으로 끝나는가."""
    return _REGION_BEFORE.search(text[max(0, pos - 12) : pos]) is not None


def _detect_address(text: str) -> list[Span]:
    cands: list[Span] = []
    for m in _ROAD_RE.finditer(text):
        name = m.group("name")
        if any(name.endswith(stop) for stop in _ROAD_STOP_SUFFIX):
            continue
        if _phone_at(text, m.start(3)):
            # '테헤란로 010-1234-5678' 의 전화번호를 건물번호로 삼키지 않는다. 도로명만 주소로 남기는 것은 앞에 시·군·구 같은
            # 지역 조각이 붙은 때뿐이다('이 번호로 010-…', '전화로 010-…' 같은 일상 말은 주소가 아니라 전화만 잡는다).
            if _region_before(text, m.start()):
                cands.append(Span(Kind.ADDRESS, m.start(), m.end("name"), 0.85, "road"))
            continue
        cands.append(Span(Kind.ADDRESS, m.start(), m.end(), 0.85, "road"))
    for m in _JIBUN_RE.finditer(text):
        name, suffix = m.group("name"), m.group("suffix")
        if name in _JIBUN_STOP:
            continue
        if _phone_at(text, m.start(3)):  # '역삼동 010-1234-5678' 의 전화번호는 지번이 아니다
            if _region_before(text, m.start()):
                cands.append(Span(Kind.ADDRESS, m.start(), m.end("name"), 0.6, "jibun"))
            continue
        explicit = ("-" in m.group(3) and suffix == "동") or m.group("bunji")
        if (
            not explicit and suffix != "동"
        ):  # 리·읍·면 은 '번지'가 있어야 한다('예약하려면 02-748' 같은 말 방지)
            continue
        cands.append(Span(Kind.ADDRESS, m.start(), m.end(), 0.85 if explicit else 0.6, "jibun"))
    for m in _DONGHO_RE.finditer(text):
        cands.append(Span(Kind.ADDRESS, m.start(), m.end(), 0.85, "dongho"))
    for m in _SIDO_RE.finditer(text):
        districts = [m.group("d1"), m.group("d2") or ""]
        if any(d in _DISTRICT_STOP for d in districts) or text.startswith("난방", m.end()):
            continue  # '서울 대도시', '경기 신도시', '중구난방'
        cands.append(Span(Kind.ADDRESS, m.start(), m.end(), 0.6, "region"))
    return _merge_adjacent(text, cands)


def _merge_adjacent(text: str, cands: list[Span]) -> list[Span]:
    """공백·쉼표로만 이어진 주소 조각을 하나의 주소로 합친다('서울시 강남구 테헤란로 152 101동 1203호')."""
    cands = sorted(cands, key=lambda s: (s.start, -s.end))
    merged: list[Span] = []
    for s in cands:
        if merged:
            last = merged[-1]
            if s.start < last.end or (
                s.start - last.end <= 2 and _ADDR_GAP.fullmatch(text[last.end : s.start])
            ):
                merged[-1] = Span(
                    Kind.ADDRESS,
                    last.start,
                    max(last.end, s.end),
                    max(last.score, s.score),
                    "address",
                )
                continue
        merged.append(s)
    return merged


# ---------------------------------------------------------------------------
# 사람 이름
# ---------------------------------------------------------------------------
SURNAMES = frozenset(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부가복태목형"
)
# 이름이 아니라 가족 호칭이므로 known_names 에 있어도 마스킹하지 않는다.
KINSHIP_TERMS = frozenset(
    "엄마 아빠 어머니 아버지 어머님 아버님 할머니 할아버지 외할머니 외할아버지 누나 언니 오빠 형 동생 삼촌 이모 고모 외삼촌 "
    "아들 딸 남편 아내 자기 여보 우리 가족 나 저 며느리 사위 손주 손자 손녀 큰아들 막내".split()
)
# 성씨로 시작하지만 직함·일반 명사인 말('이사님', '고객님', '선생님' …). 호칭 휴리스틱의 오탐을 줄인다.
_HONORIFIC_STOP = frozenset(
    "이사 사장 부장 과장 팀장 회장 고객 선생 교수 대표 원장 실장 점장 국장 차장 대리 주임 사원 기사 반장 조장 위원 주인 "
    "국민 장군 신부 공주 왕자 고모 부모 어머 사모 이모 장모 서방 방장 하느 천사 도우미 사부 고구마 나리 지도 구성원 "
    "가장 주부 문의 정리 박수 한분 기자 간사 감사 장교 선배 후배 조교 소장 이장 사감 의원 부인 주민 안내 "
    "하나 박사 형수 목사 변호 부처 도련 강사 사범 서기 주치 신도 방문 성인 도사 성모 전문 한의".split()
)
# 호칭 앞에 공백이 있는 꼴('사용자 님', '모두 님')은 이름이 아닌 일반어일 가능성이 커서 더 엄격하게 거른다.
_SPACED_STOP = frozenset("모두 손주 손자 배송 최고 신청 노인 어르신 조부모 조부 손녀 모든".split())


def _spaced_generic(name: str) -> bool:
    """'사용자 님'·'정대표 님' 같은 역할·직함 말(끝이 '자', 뒤쪽이 직함 불용어, 일반어 목록)이면 True."""
    return (
        name[-1] == "자"
        or name in _SPACED_STOP
        or name[1:] in _HONORIFIC_STOP
        or name[:2] in _SPACED_STOP
    )


_PARTICLES = tuple(
    sorted(
        [
            "에게서", "한테서", "께서는", "께서", "에게", "한테", "이랑", "이는", "이가", "이도", "이야", "이고",
            "이라고", "이라", "이다", "인데", "고", "며", "지만", "이니", "이에요", "이예요", "예요", "에서", "으로", "까지", "부터",
            "처럼", "보다", "이", "가", "은", "는", "을", "를", "와", "과", "의", "도", "랑", "야", "아", "씨",
            "님", "만", "에", "로", "께", "군", "양", "네", "이한테", "이에게",
        ],
        key=len,
        reverse=True,
    )
)  # fmt: skip
# 이름 사전의 2글자 별칭('김하나' -> '하나')이 일반어와 겹치는 경우를 막는 짧은 내장 목록. 전체 이름(성+이름) 일치는 항상 허용한다.
COMMON_WORD_ALIASES = frozenset(
    "하나 수정 지원 보라 나은 미래 유리 지연 소망 하늘 사랑 보람 아름 슬기 소원 다운 나래 가을 바다 "
    "주희 나비 이슬 희망 한결 다솜 새봄 고은 은혜 정리 선물 진실 예쁜 은총 승리 우주 별이".split()
)
_TITLE_NEXT = _PARTICLES + ("께서", "이", "가")
_HONORIFIC_RE = re.compile(
    rf"(?<![가-힣])(?P<n>[{''.join(sorted(SURNAMES))}][가-힣]{{1,2}})(?P<sp> ?)(?P<t>선생님|님|씨|군|양)"
)


def _name_end_ok(text: str, end: int) -> bool:
    """이름 바로 뒤가 글자 끝·비한글이거나, 조사(한두 개 이어 붙은 것까지)로 끝나는 어절이면 이름으로 본다."""
    pos = end
    for _ in range(3):  # 조사는 최대 세 개까지('에게는', '씨고', '와의')
        if pos >= len(text) or not _is_hangul(text[pos]):
            return True
        matched = next((p for p in _PARTICLES if text.startswith(p, pos)), None)
        if matched is None:
            return False
        pos += len(matched)
    return pos >= len(text) or not _is_hangul(text[pos])


def _detect_person_known(text: str, known_names: tuple[str, ...]) -> list[Span]:
    """가족 구성원 이름 사전과 정확히 일치하는 어절에서 이름 부분만 잡는다(뒤에 조사가 붙어도 이름 부분만)."""
    entries: dict[str, tuple[str, float]] = {}
    for raw in known_names:
        name = " ".join(str(raw).split())
        if len(name) < 2 or name in KINSHIP_TERMS:
            continue
        entries[name] = (name, 0.9 if len(name) >= 3 else 0.75)
    # 성 + 이름 3글자('김민수')면 이름만 부르는 말('민수야')도 같은 사람으로 묶는다.
    for name in list(entries):
        if len(name) == 3 and name[0] in SURNAMES and all(_is_hangul(c) for c in name):
            alias = name[1:]
            if (
                alias not in entries
                and alias not in KINSHIP_TERMS
                and alias not in COMMON_WORD_ALIASES
            ):
                entries[alias] = (name, 0.8)
    spans = []
    for name in sorted(entries, key=len, reverse=True):
        canonical, score = entries[name]
        pattern = re.compile(rf"(?<![가-힣A-Za-z0-9]){re.escape(name)}")
        for m in pattern.finditer(text):
            if _name_end_ok(text, m.end()):
                spans.append(Span(Kind.PERSON, m.start(), m.end(), score, "name_dict", canonical))
    return spans


def _detect_person_honorific(text: str) -> list[Span]:
    """사전에 없는 이름은 '성씨 + 이름 + 호칭' 꼴일 때만 낮은 점수로 잡는다(호칭 필수: '김치', '박수', '정리' 오탐 방지)."""
    spans = []
    for m in _HONORIFIC_RE.finditer(text):
        name, title = m.group("n"), m.group("t")
        if name in _HONORIFIC_STOP or name[:2] in _HONORIFIC_STOP:
            continue
        if m.group("sp") and _spaced_generic(name):
            continue
        if m.group("sp") and title in (
            "군",
            "양",
        ):  # 띄어 쓴 '군'·'양'은 '고추장 양이 많아' 같은 일반 문장과 구분이 안 되어 제외
            continue
        if title in ("씨", "군", "양") and len(name) != 3:  # '고추씨', '오이씨' 같은 말 방지
            continue
        end = m.end()
        if end < len(text) and _is_hangul(text[end]):
            if not any(text.startswith(p, end) for p in _TITLE_NEXT):
                continue
        spans.append(Span(Kind.PERSON, m.start("n"), m.end("n"), 0.5, "name_honorific"))
    return spans


# ---------------------------------------------------------------------------
# 통합
# ---------------------------------------------------------------------------
def _resolve(cands: list[Span]) -> list[Span]:
    """겹치는 후보 중 위험도 높은 것 -> 긴 것 -> 점수 높은 것 순으로 하나만 남기고 시작 위치순으로 돌려준다."""
    order = sorted(cands, key=lambda s: (RISK_RANK[s.risk], -s.length, -s.score, s.start))
    chosen: list[Span] = []
    starts: list[int] = []
    ends: list[int] = []
    for s in order:  # 이미 고른 구간은 겹치지 않으므로 시작 위치순 이웃 둘만 보면 된다(O(n log n))
        i = bisect_left(starts, s.start)
        if i > 0 and ends[i - 1] > s.start:
            continue
        if i < len(starts) and starts[i] < s.end:
            continue
        starts.insert(i, s.start)
        ends.insert(i, s.end)
        chosen.append(s)
    chosen.sort(key=lambda s: s.start)
    return chosen


def detect(text: str, known_names: tuple[str, ...] | list[str] = ()) -> list[Span]:
    """text 에서 개인정보 구간을 찾아 겹치지 않게 정리해 시작 위치순으로 돌려준다.

    known_names 는 그 가족 구성원의 실제 이름·표시 이름이다(2자 이상). 값은 이 호출 안에서만 쓰고 저장하지 않는다.
    """
    if not text:
        return []
    text = text.translate(_FOLD)  # 전각·대시 변형을 반각으로(길이 불변)
    if _INVISIBLE.search(
        text
    ):  # 폭 없는 공백이 낀 번호('0<ZWSP>10-1234-5678')도 찾도록 지우고 탐지한 뒤 원문 위치로 되돌린다
        return _detect_without_invisible(text, known_names)
    return _detect_folded(text, known_names)


def _detect_without_invisible(text: str, known_names: tuple[str, ...] | list[str]) -> list[Span]:
    keep = [i for i, ch in enumerate(text) if ch not in INVISIBLE_CHARS]
    plain = "".join(text[i] for i in keep)
    out: list[Span] = []
    for s in _detect_folded(plain, known_names):
        out.append(Span(s.kind, keep[s.start], keep[s.end - 1] + 1, s.score, s.source, s.canonical))
    return out


def _detect_folded(text: str, known_names: tuple[str, ...] | list[str]) -> list[Span]:
    cands: list[Span] = []
    cands += _detect_secret(text)
    cands += _detect_rrn(text)
    cands += _detect_card(text)
    cands += _detect_account(text)
    cands += _detect_phone(text)
    cands += _detect_email(text)
    cands += _detect_address(text)
    cands += _detect_person_known(text, tuple(known_names))
    cands += _detect_person_honorific(text)
    return _resolve(cands)
