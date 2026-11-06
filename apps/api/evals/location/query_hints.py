"""질문 문장에서 사람·날짜·시각을 규칙으로 뽑는다(LLM 없음).

실제 서비스에서는 에이전트(LLM)가 검색 도구를 부를 때 사람·날짜·시각을 인자로 넘긴다. 이 평가는 키 없이 돌아야 해서
그 역할을 이 규칙이 대신한다. 여기서 나온 점수는 '인자가 맞게 추출됐을 때의 검색 품질'이고, 에이전트가 인자를 맞게
뽑는지는 답변 평가(LLM 사용)에서 따로 본다.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

WEEKDAYS = "월화수목금토일"


@dataclass(frozen=True)
class Hints:
    person_ids: list[str] | None  # 질문에 이름이 나온 사람(없으면 None = 볼 수 있는 모두)
    date_range: tuple[datetime, datetime] | None  # 질문이 가리키는 하루(없으면 None)
    at: datetime | None  # 하루와 시각이 함께 나온 경우 그 시각
    kinds: tuple[str, ...] | None = (
        None  # 질문의 성격에 맞는 조각 종류(횟수 → place, 순서 → move·day)
    )


def _day_range(day: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(day.date(), time(0))
    return start, start + timedelta(days=1)


def _date(question: str, now: datetime) -> datetime | None:
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", question)
    if m:
        return datetime(now.year, int(m.group(1)), int(m.group(2)))
    for word, back in (("그저께", 2), ("어제", 1), ("오늘", 0)):
        if word in question:
            return datetime.combine((now - timedelta(days=back)).date(), time(0))
    m = re.search(r"지난\s*([월화수목금토일])요일", question)
    if m:
        target = WEEKDAYS.index(m.group(1))
        back = (now.weekday() - target) % 7 or 7  # 오늘이 그 요일이어도 지난주로 본다
        return datetime.combine((now - timedelta(days=back)).date(), time(0))
    return None


def _clock(question: str) -> time | None:
    m = re.search(r"(오전|오후|아침|새벽|저녁|낮)?\s*(\d{1,2})시(\s*반)?", question)
    if not m:
        return None
    hour = int(m.group(2))
    if m.group(1) in ("오후", "저녁") and hour < 12:
        hour += 12
    return time(hour % 24, 30 if m.group(3) else 0)


COUNT_WORDS = ("몇 번", "횟수", "몇 건", "총 몇", "몇 번째")
SEQUENCE_WORDS = ("다음", "끝나고", "뒤", "직후", "돌아간", "어디로 이동", "어디로 갔")


def _kinds(question: str) -> tuple[str, ...] | None:
    if any(w in question for w in COUNT_WORDS):
        return ("place",)
    if any(w in question for w in SEQUENCE_WORDS):
        return ("move", "day")
    return None


def extract(question: str, people: dict[str, str], now: datetime) -> Hints:
    """people 은 사람 id → 이름. 질문에 이름이 나온 사람, 가리키는 날, 시각을 돌려준다."""
    named = [pid for pid, name in people.items() if name in question]
    day = _date(question, now)
    clock = _clock(question)
    return Hints(
        person_ids=named or None,
        date_range=_day_range(day) if day else None,
        at=datetime.combine(day.date(), clock) if day and clock else None,
        kinds=_kinds(question),
    )
