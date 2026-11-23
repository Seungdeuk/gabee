"""지출 삭제 제안의 '대상 특정' 검사: 사용자 문장이 이 지출을 가리켰는지 서버가 직접 확인한다.

모델이 고른 `expense_id` 가 내 지출이라는 것(`service.open_own_expense`)만으로는 사용자가 그 지출을 지우라고 했는지 알 수 없다
('지난번에 낸 지출 지워 줘' 같은 모호한 요청에 모델이 임의로 하나를 골라 삭제 확인 카드를 만든 사례, T35 S2-B1 ambig-02).
그래서 제안을 만들기 전에 사용자 문장이 이 지출을 **제목·금액·날짜 중 하나 이상**으로 가리키는지, 그리고 같은 달 내 지출 중
이 지출이 가장 잘 맞는 단 하나인지 본다. 이 모듈은 DB 를 읽지 않는 순수 함수만 둔다(시험이 쉽고, 규칙이 한 곳에 있다).

한계(문서화): 날짜는 'N월 N일'·'N일'·ISO·'N/N' 만 읽고 '어제'·'지난주' 같은 상대 표현은 읽지 않는다. 금액은 '80,000원'·'8만원'·'3만5천원'·'5천원'
같은 흔한 표기만 읽는다. 읽지 못하면 안전한 쪽(되묻기)으로 거절한다.
"""

import re
from collections.abc import Sequence

# 어느 지출에나 붙는 말은 제목 낱말로 치지 않는다
_GENERIC = frozenset(
    {"지출", "비용", "결제", "내역", "정산", "항목", "돈", "지난번", "그거", "이거"}
)
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[0-9A-Za-z가-힣]+")
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_KO_DATE = re.compile(r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일")
_SLASH = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")
_MAN = re.compile(r"(\d[\d,]*)\s*만\s*(?:(\d[\d,]*)\s*천\s*|(\d[\d,]*)\s*)?원?")
_CHEON = re.compile(r"(\d[\d,]*)\s*천\s*원?")
_PLAIN = re.compile(r"(?<![\d/-])(\d{1,3}(?:,\d{3})+|\d{3,})(?![\d/-])\s*원?")


def _norm(text: str) -> str:
    return _SPACE.sub("", text).lower()


def _int(raw: str) -> int:
    return int(raw.replace(",", ""))


def mentioned_amounts(question: str) -> set[int]:
    """문장에 쓴 금액(원). 단위·쉼표가 있거나 세 자리 이상 숫자만 금액으로 읽는다(날짜의 작은 숫자와 섞이지 않게)."""
    found: set[int] = set()

    def man(m: re.Match) -> str:
        value = _int(m.group(1)) * 10_000
        if m.group(2):
            value += _int(m.group(2)) * 1_000
        elif m.group(3):
            value += _int(m.group(3))
        found.add(value)
        return " "

    def cheon(m: re.Match) -> str:
        found.add(_int(m.group(1)) * 1_000)
        return " "

    # 이미 읽은 구간은 지우고 다음 표기를 읽는다('3만5천원' 의 '5천원' 이 따로 금액으로 읽히지 않게)
    rest = _MAN.sub(man, question)
    rest = _CHEON.sub(cheon, rest)
    for m in _PLAIN.finditer(rest):
        found.add(_int(m.group(1)))
    return found


def mentioned_dates(question: str) -> list[tuple[int | None, int | None, int]]:
    """문장에 쓴 날짜: (연, 월, 일) 에서 모르는 값은 None. 'N일' 만 쓰면 (None, None, N)."""
    found: list[tuple[int | None, int | None, int]] = []
    for m in _ISO.finditer(question):
        found.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _KO_DATE.finditer(question):
        found.append((None, int(m.group(1)) if m.group(1) else None, int(m.group(2))))
    for m in _SLASH.finditer(question):
        found.append((None, int(m.group(1)), int(m.group(2))))
    return found


def _title_match_length(question: str, title: str) -> int:
    """문장에 들어 있는 제목(또는 제목 낱말)의 글자 수. 0 이면 제목을 말하지 않은 것이다. 길수록 더 구체적으로 가리킨 것이다."""
    flat_q = _norm(question)
    flat_t = _norm(title)
    if len(flat_t) >= 2 and flat_t in flat_q:
        return len(flat_t)
    return max(
        (
            len(w)
            for w in _WORD.findall(title)
            if len(w) >= 2 and w not in _GENERIC and w.lower() in flat_q
        ),
        default=0,
    )


def _date_matches(question: str, expense_date: str) -> bool:
    try:
        year, month, day = (int(p) for p in expense_date.split("-"))
    except ValueError:
        return False
    for y, mo, d in mentioned_dates(question):
        if d == day and (mo is None or mo == month) and (y is None or y == year):
            return True
    return False


def match_strength(question: str, expense) -> tuple[int, int]:
    """사용자 문장이 이 지출을 가리키는 정도: (맞은 종류 수(제목·금액·날짜), 맞은 제목의 글자 수). (0, 0) 이면 가리키지 않은 것이다.
    종류 수가 같으면 제목을 더 길게 말한 쪽이 더 구체적이다('수진이 학원비' 는 제목이 '학원비' 인 지출보다 '수진이 학원비' 에 더 잘 맞는다)."""
    title = _title_match_length(question, expense.title)
    kinds = (
        (1 if title else 0)
        + (1 if expense.amount in mentioned_amounts(question) else 0)
        + (1 if _date_matches(question, expense.date) else 0)
    )
    return kinds, title


def _lines(pool: Sequence, limit: int = 5) -> str:
    rows = [f"{e.title} {e.amount:,}원({e.date})" for e in list(pool)[:limit]]
    more = f" 외 {len(pool) - limit}건" if len(pool) > limit else ""
    return ", ".join(rows) + more


def ensure_identified(question: str, target, pool: Sequence) -> None:
    """사용자 문장이 `target` 을 특정하지 못하면 ValueError(모델이 사용자에게 그대로 되묻도록 쓴 문장).

    pool 은 같은 달의 내 지출 전체(대상 포함). 대상이 제목·금액·날짜 중 하나도 맞지 않거나, 다른 지출이 같거나 더 잘 맞으면 거절한다.
    """
    own = match_strength(question or "", target)
    if own == (0, 0):
        raise ValueError(
            "사용자 문장에 어느 지출인지 가리키는 말(제목·금액·날짜)이 없어서 삭제를 제안할 수 없어요. "
            "삭제 확인 카드를 만들지 말고 사용자에게 어느 지출을 지울지 물어보세요. 이 달 내 지출: "
            + _lines(pool)
        )
    rivals = [
        e
        for e in pool
        if getattr(e, "id", None) != getattr(target, "id", None)
        and match_strength(question, e) >= own
    ]
    if rivals:
        raise ValueError(
            "사용자가 말한 내용에 해당하는 지출이 여러 건이라 어느 지출인지 정할 수 없어요. "
            "삭제 확인 카드를 만들지 말고 사용자에게 어느 지출인지 물어보세요: "
            + _lines([target, *rivals])
        )
