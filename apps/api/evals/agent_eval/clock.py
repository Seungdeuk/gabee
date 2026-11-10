"""평가 프로세스 안에서만 현재 시각을 고정한다. 운영 코드는 바꾸지 않는다.

앱은 시각을 모듈마다 `datetime.now(...)` 로 읽고 주입할 자리가 없다. 그래서 평가가 켜 둔 동안 `app.` 모듈들이 가진
`datetime` 이름만 기준 시각에서 시작하는 시계로 바꿔 끼운다(`date.today()` 는 `date` 이름을 같은 방식으로).
시계는 호출할 때마다 1밀리초씩 앞으로 가서 같은 시각에 만든 행의 정렬이 뒤섞이지 않고, 하루를 넘지 않는 한 날짜는 그대로다.
끝나면 원래 이름으로 되돌린다. 평가 프로세스 밖(운영 서버·다른 시험)에는 영향이 없다.
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
REFERENCE_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=KST)  # 화요일 낮 12시(한국 시간)
TICK = timedelta(milliseconds=1)
MAX_TICKS = (
    43_000_000  # 1밀리초씩 약 11.9시간: 기준 시각(낮 12시) 다음 자정 전에 멈춘다(넘으면 오류)
)


def make_clock(now: datetime) -> tuple[type[datetime], type[date]]:
    """`now` 에서 시작하는 (datetime 대신 쓸 클래스, date 대신 쓸 클래스)."""
    if now.tzinfo is None:
        raise ValueError("기준 시각에는 시간대가 있어야 한다")
    state = {"now": now.astimezone(UTC), "ticks": 0}

    def advance() -> datetime:
        state["ticks"] += 1
        if state["ticks"] > MAX_TICKS:
            raise RuntimeError("고정 시계가 하루 분량을 넘어 흘렀다(날짜가 바뀐다)")
        state["now"] += TICK
        return state["now"]

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            current = advance()
            return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):  # noqa: D102
            return advance().replace(tzinfo=None)

    class FrozenDate(date):
        @classmethod
        def today(cls):  # noqa: D102
            return advance().astimezone(KST).date()

    return FrozenDatetime, FrozenDate


@contextmanager
def frozen_clock(now: datetime = REFERENCE_NOW, prefix: str = "app.") -> Iterator[None]:
    fake_datetime, fake_date = make_clock(now)
    patched: list[tuple[object, str, object]] = []
    for name, module in list(sys.modules.items()):
        if not name.startswith(prefix) or module is None:
            continue
        for attr, fake, real in (("datetime", fake_datetime, datetime), ("date", fake_date, date)):
            if getattr(module, attr, None) is real:
                patched.append((module, attr, real))
                setattr(module, attr, fake)
    try:
        yield
    finally:
        for module, attr, real in patched:
            setattr(module, attr, real)
