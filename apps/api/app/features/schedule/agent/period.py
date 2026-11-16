"""사용자 문장에서 기간 표현(오늘·내일·이번 주·다음 달·N월 N일·요일 …)을 LLM 없이 뽑는다.

뽑히면 그 기간의 일정만 모델에 보내고, 못 뽑으면 None 을 돌려줘 호출한 쪽이 가까운 순 상한으로 대신한다.
못 뽑는 표현이 있어도 일정을 못 찾는 일은 없다(그때는 넓게 보낸다).
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
MARGIN = timedelta(days=1)  # 기간 앞뒤로 하루씩 더 보낸다(밤샘·경계 일정 대비)


@dataclass(frozen=True)
class Period:
    """뽑은 기간. also 는 연도가 없는 날짜가 지난 해·다가올 해 중 어느 쪽인지 가를 수 없어 둘 다 보내는 때의 다른 쪽 구간이고,
    note 는 그 선택을 모델에게 알려 답 끝에 안내 멘트를 붙이게 하는 글이다(둘 다 비교(==)에는 쓰지 않는다)."""

    start: date
    end: date
    also: tuple[tuple[date, date], ...] = field(default=(), compare=False)
    note: str = field(default="", compare=False)

    def widened(self) -> "Period":
        return Period(
            self.start - MARGIN,
            self.end + MARGIN,
            tuple((a - MARGIN, b + MARGIN) for a, b in self.also),
            self.note,
        )

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end or any(a <= day <= b for a, b in self.also)

    def label(self) -> str:
        text = f"{self.start:%Y-%m-%d} ~ {self.end:%Y-%m-%d}"
        for a, b in self.also:
            text += f" 또는 {a:%Y-%m-%d} ~ {b:%Y-%m-%d}"
        return text


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _month_range(year: int, month: int) -> Period:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return Period(first, nxt - timedelta(days=1))


def _shift_month(today: date, delta: int) -> tuple[int, int]:
    index = today.year * 12 + today.month - 1 + delta
    return index // 12, index % 12 + 1


_PAST = re.compile(r"[았었였했갔왔]")  # 과거형: 했더라·였지·있었·갔어 …
_FUTURE = re.compile(
    r"가자|가야|갈래|갈게|가려|잡아|넣어|등록|예약|추가|하자|할게|할래|해야|할까|갈까|예정|시켜|바꿔|옮겨|미뤄|만나자|먹자|보자|언제야|언제지|언제예요"
)
BOTH_RATIO = 1.5  # 지난 쪽과 다가올 쪽의 거리 비가 이보다 작으면 중간이라 둘 다 보낸다


def _tense(text: str) -> str:
    """문장의 시제: past / future / ''(신호 없음 또는 둘 다 있음)."""
    past, future = bool(_PAST.search(text)), bool(_FUTURE.search(text))
    if past and not future:
        return "past"
    if future and not past:
        return "future"
    return ""


def _label(p: Period, day: int | None) -> str:
    return f"{p.start.year}년 {p.start.month}월" + (f" {p.start.day}일" if day else "")


def _how(year: int, today: date) -> str:
    return {0: "올해", 1: "내년", -1: "작년"}.get(year - today.year, f"{year}년")


def _distance(p: Period, today: date) -> int:
    if p.start <= today <= p.end:
        return 0
    return min(abs((p.start - today).days), abs((p.end - today).days))


def _pick_year(
    today: date, month: int, day: int | None, tense: str
) -> tuple[Period, tuple[tuple[date, date], ...], str] | None:
    """연도 없는 N월(N일)의 해를 정한다. 오늘이 속하면 그것. 과거형이면 가장 가까운 지난 것, 미래형이면 가장 가까운 다가올 것.
    신호가 없으면 더 가까운 쪽(오늘에서 거리)이고 다른 해를 고르는 안내를 붙인다. 두 쪽이 비슷하게 가까우면(중간) 둘 다 보낸다.
    돌려주는 값: (주 기간, 함께 보낼 다른 구간, 모델에게 줄 안내). 없는 날짜면 None."""
    cands: list[Period] = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cands.append(
                Period(date(year, month, day), date(year, month, day))
                if day
                else _month_range(year, month)
            )
        except ValueError:
            continue
    if not cands:
        return None
    for p in cands:
        if p.start <= today <= p.end:
            return p, (), ""
    past = max((p for p in cands if p.end < today), key=lambda p: p.end, default=None)
    future = min((p for p in cands if p.start > today), key=lambda p: p.start, default=None)
    if past is None or future is None:
        return (past or future), (), ""
    if tense == "past":
        return past, (), ""
    if tense == "future":
        return future, (), ""
    d_past, d_future = _distance(past, today), _distance(future, today)
    near, far = (past, future) if d_past <= d_future else (future, past)
    ratio = max(d_past, d_future) / max(min(d_past, d_future), 1)
    if ratio < BOTH_RATIO:
        note = (
            f"연도 없는 날짜라 지난 날짜({_label(past, day)})와 다가올 날짜({_label(future, day)})가 비슷하게 가까워 "
            "두 날짜를 모두 보여 준다. 각각 일정이 있는지 밝히고 없으면 없다고 말한다."
        )
        return near, ((far.start, far.end),), note
    note = (
        f"연도 없는 날짜라 {_label(near, day)}로 보았다. 답 끝에 "
        f"\"{_label(far, day)}이 필요하시면 '{_how(far.start.year, today)}'라고 말씀해 주세요\"를 덧붙인다."
    )
    return near, (), note


_WEEK_WORDS = (
    (re.compile(r"다다음주"), 2),
    (re.compile(r"다음주|내주"), 1),
    (re.compile(r"이번주|금주"), 0),
    (re.compile(r"지난주|저번주"), -1),
)
_DAY_WORDS = (
    (re.compile(r"그저께|엊그제"), -2),
    (re.compile(r"어제"), -1),
    (re.compile(r"오늘"), 0),
    (re.compile(r"내일"), 1),
    (re.compile(r"모레"), 2),
    (re.compile(r"글피"), 3),
)
_MONTH_WORDS = (
    (re.compile(r"다음달|내달"), 1),
    (re.compile(r"이번달|이달"), 0),
    (re.compile(r"지난달|저번달"), -1),
)
_YEAR_WORDS = (
    (re.compile(r"내년"), 1),
    (re.compile(r"올해|금년"), 0),
    (re.compile(r"작년|지난해"), -1),
)
# 구어 줄임말(낼·담주·담달). "보낼"·"해낼"처럼 다른 낱말의 일부와 헷갈리지 않게 앞뒤가 한글이 아닐 때만 본다
_SLANG_WEEK = ((re.compile(r"(?<![가-힣])담주(?![가-힣])"), 1),)
_SLANG_DAY = (
    (re.compile(r"(?<![가-힣])낼모레(?![가-힣])"), 2),
    (re.compile(r"(?<![가-힣])낼(?=$|[^가-힣]|은|도|부터|까지|쯤|엔|에(?![가-힣]))"), 1),
)
_SLANG_MONTH = ((re.compile(r"(?<![가-힣])담달(?![가-힣])"), 1),)
_MONTH_DAY = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
_MONTH_ONLY = re.compile(r"(?<!\d)(\d{1,2})월(?!\s*\d{1,2}일)")
_WEEKDAY = re.compile(r"([월화수목금토일])(?:요일|욜)")  # 화욜·일욜 같은 구어형도
_WEEKEND = re.compile(r"주말")


def extract(text: str, today: date) -> Period | None:
    """문장에서 기간을 뽑는다. 여러 표현이 있으면 모두 아우르는 구간(처음~마지막)을 돌려준다. 없으면 None."""
    t = re.sub(r"\s+", "", text)
    raw = re.sub(r"\s+", " ", text)  # 줄임말은 낱말 경계를 봐야 해서 공백을 남긴 글로 찾는다
    tense = _tense(raw)
    found: list[Period] = []
    extras: list[tuple[date, date]] = []
    notes: list[str] = []

    week_offset = next((offset for pattern, offset in _WEEK_WORDS if pattern.search(t)), None)
    if week_offset is None:
        week_offset = next((o for pattern, o in _SLANG_WEEK if pattern.search(raw)), None)
    weekday = _WEEKDAY.search(t)
    if week_offset is not None:
        monday = _monday(today) + timedelta(weeks=week_offset)
        if weekday:  # 다음 주 월요일처럼 주와 요일이 함께 나오면 그 하루
            day = monday + timedelta(days=WEEKDAYS[weekday.group(1)])
            found.append(Period(day, day))
        elif _WEEKEND.search(t):
            found.append(Period(monday + timedelta(days=5), monday + timedelta(days=6)))
        else:
            found.append(Period(monday, monday + timedelta(days=6)))
    elif weekday:  # 요일만 나오면 오늘 포함 앞으로 가장 가까운 그 요일
        ahead = (WEEKDAYS[weekday.group(1)] - today.weekday()) % 7
        day = today + timedelta(days=ahead)
        found.append(Period(day, day))
    elif _WEEKEND.search(t):
        monday = _monday(today)
        found.append(Period(monday + timedelta(days=5), monday + timedelta(days=6)))

    for pattern, offset in _DAY_WORDS:
        if pattern.search(t):
            day = today + timedelta(days=offset)
            found.append(Period(day, day))
    for pattern, offset in _SLANG_DAY:
        if pattern.search(raw):
            day = today + timedelta(days=offset)
            found.append(Period(day, day))

    for pattern, offset in _MONTH_WORDS:
        if pattern.search(t):
            found.append(_month_range(*_shift_month(today, offset)))
    for pattern, offset in _SLANG_MONTH:
        if pattern.search(raw):
            found.append(_month_range(*_shift_month(today, offset)))

    for pattern, offset in _YEAR_WORDS:
        if pattern.search(t):
            year = today.year + offset
            found.append(Period(date(year, 1, 1), date(year, 12, 31)))

    for month, day in _MONTH_DAY.findall(t):
        picked = _pick_year(today, int(month), int(day), tense)
        if picked:
            found.append(picked[0])
            extras.extend(picked[1])
            if picked[2]:
                notes.append(picked[2])
    for month in _MONTH_ONLY.findall(_MONTH_DAY.sub("", t)):
        if 1 <= int(month) <= 12:
            picked = _pick_year(today, int(month), None, tense)
            if picked:
                found.append(picked[0])
                extras.extend(picked[1])
                if picked[2]:
                    notes.append(picked[2])

    if not found:
        return None
    return Period(
        min(p.start for p in found),
        max(p.end for p in found),
        tuple(extras),
        " ".join(notes),
    )


# 일정을 옮기거나 바꾸는 말. 이런 문장의 날짜는 옮길 날짜일 수 있어, 그 기간으로 목록을 거르면 대상 일정이 빠진다
_MOVE = re.compile(r"옮|미뤄|미룰|미루|당겨|앞당|뒤로|변경|바꿔|바꿀|바꾸|수정")


def extract_for_prompt(text: str, today: date) -> Period | None:
    """모델에 보낼 일정 목록을 거르는 기간. 수정·이동 문장이면 None(가까운 순으로 넓게 보내고 부족하면 모델이 다시 요청한다)."""
    if _MOVE.search(text):
        return None
    return extract(text, today)


MAX_SPAN = timedelta(days=365)  # 서버가 읽어 둔 범위(과거·미래 1년)와 같다


def from_model(start: str, end: str, today: date) -> Period | None:
    """모델이 돌려준 기간(YYYY-MM-DD)을 검증한다. 형식·순서가 틀리거나 읽어 둔 범위(오늘 기준 과거·미래 1년) 밖이면 None,
    일부만 겹치면 범위 안으로 자른다. 모델 값은 서버가 이미 읽은 일정을 거르는 데만 쓴다(DB 를 직접 조회하지 않는다)."""
    try:
        first, last = date.fromisoformat(start.strip()), date.fromisoformat(end.strip())
    except (ValueError, AttributeError):
        return None
    if first > last:
        return None
    lo, hi = today - MAX_SPAN, today + MAX_SPAN
    if last < lo or first > hi:
        return None
    return Period(max(first, lo), min(last, hi))
