"""사용자 문장에서 기간 표현(오늘·내일·이번 주·다음 달·N월 N일·요일 …)을 LLM 없이 뽑는다.

뽑히면 그 기간의 일정만 모델에 보내고, 못 뽑으면 None 을 돌려줘 호출한 쪽이 가까운 순 상한으로 대신한다.
못 뽑는 표현이 있어도 일정을 못 찾는 일은 없다(그때는 넓게 보낸다).
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
MARGIN = timedelta(days=1)  # 기간 앞뒤로 하루씩 더 보낸다(밤샘·경계 일정 대비)


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def widened(self) -> "Period":
        return Period(self.start - MARGIN, self.end + MARGIN)

    def label(self) -> str:
        return f"{self.start:%Y-%m-%d} ~ {self.end:%Y-%m-%d}"


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _month_range(year: int, month: int) -> Period:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return Period(first, nxt - timedelta(days=1))


def _shift_month(today: date, delta: int) -> tuple[int, int]:
    index = today.year * 12 + today.month - 1 + delta
    return index // 12, index % 12 + 1


def _closest(today: date, month: int, day: int | None) -> Period | None:
    """N월(N일)이 가리키는 해를 가장 가까운 해(작년·올해·내년)로 정한다. 없는 날짜면 None."""
    best: Period | None = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            period = (
                Period(date(year, month, day), date(year, month, day))
                if day
                else _month_range(year, month)
            )
        except ValueError:
            continue
        if best is None or abs((period.start - today).days) < abs((best.start - today).days):
            best = period
    return best


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
_MONTH_DAY = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
_MONTH_ONLY = re.compile(r"(?<!\d)(\d{1,2})월(?!\s*\d{1,2}일)")
_WEEKDAY = re.compile(r"([월화수목금토일])요일")
_WEEKEND = re.compile(r"주말")


def extract(text: str, today: date) -> Period | None:
    """문장에서 기간을 뽑는다. 여러 표현이 있으면 모두 아우르는 구간(처음~마지막)을 돌려준다. 없으면 None."""
    t = re.sub(r"\s+", "", text)
    found: list[Period] = []

    week_offset = next((offset for pattern, offset in _WEEK_WORDS if pattern.search(t)), None)
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

    for pattern, offset in _MONTH_WORDS:
        if pattern.search(t):
            found.append(_month_range(*_shift_month(today, offset)))

    for pattern, offset in _YEAR_WORDS:
        if pattern.search(t):
            year = today.year + offset
            found.append(Period(date(year, 1, 1), date(year, 12, 31)))

    for month, day in _MONTH_DAY.findall(t):
        period = _closest(today, int(month), int(day))
        if period:
            found.append(period)
    for month in _MONTH_ONLY.findall(_MONTH_DAY.sub("", t)):
        if 1 <= int(month) <= 12:
            period = _closest(today, int(month), None)
            if period:
                found.append(period)

    if not found:
        return None
    return Period(min(p.start for p in found), max(p.end for p in found))


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
