"""용돈 주기의 지급일 계산(DB 와 무관한 순수 함수)."""

import calendar
from datetime import date, timedelta

MAX_CATCH_UP = 24  # 오래 안 열었을 때 한 번에 따라잡는 지급일의 상한


def due_dates(cycle: str, day: int, start: date, upto: date) -> list[date]:
    """start 이상 upto 이하의 지급일(오래된 순). 상한을 넘으면 가장 최근 MAX_CATCH_UP 개만 남긴다.
    - weekly: day 는 요일(0=월 … 6=일)
    - monthly: day 는 1~31, 그 달에 없는 날이면 말일"""
    out: list[date] = []
    if cycle == "weekly":
        d = start + timedelta(days=(day - start.weekday()) % 7)
        while d <= upto:
            out.append(d)
            d += timedelta(days=7)
    else:
        year, month = start.year, start.month
        while date(year, month, 1) <= upto:
            d = date(year, month, min(day, calendar.monthrange(year, month)[1]))
            if start <= d <= upto:
                out.append(d)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out[-MAX_CATCH_UP:]


def next_due(cycle: str, day: int, today: date) -> date:
    """오늘 포함 다음 지급일."""
    if cycle == "weekly":
        return today + timedelta(days=(day - today.weekday()) % 7)
    year, month = today.year, today.month
    for _ in range(2):
        d = date(year, month, min(day, calendar.monthrange(year, month)[1]))
        if d >= today:
            return d
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return d
