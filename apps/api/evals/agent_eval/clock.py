"""평가 프로세스 안에서만 현재 시각을 고정한다. 운영 코드는 바꾸지 않는다.

앱은 시각을 모듈마다 `datetime.now(...)` 로 읽고 주입할 자리가 없다. 그래서 평가가 켜 둔 동안 `app.` 모듈들이 가진
`datetime` 이름만 기준 시각에서 시작하는 시계로 바꿔 끼운다(`date.today()` 는 `date` 이름을 같은 방식으로).
시계는 호출할 때마다 1밀리초씩 앞으로 가서 같은 시각에 만든 행의 정렬이 뒤섞이지 않고, 기준 시각의 다음 한국 시간 자정 전에
멈춘다(넘으면 오류). 끝나면 원래 이름으로 되돌린다. 평가 프로세스 밖(운영 서버·다른 시험)에는 영향이 없다.

한계(코드로 막는 것과 못 막는 것)
- 켜는 순간 이미 불러온 모듈만 바꿀 수 있어서 켜기 전에 `app.main` 을 불러온다(모든 기능 모듈이 딸려 온다). 그래도 켠 뒤에 새로 불러온
  `app.` 모듈이 실제 시각을 읽도록 남아 있으면 끝날 때 오류로 알린다.
- 시계는 겹쳐 열 수 없다(안쪽 기준 시각이 조용히 무시되는 것을 막으려고 오류). 시계는 한 번 열면 계속 흐르므로 한 실행 안의 모든 사례가
  같은 날짜를 보고, 같은 날짜를 유지하는 상한(자정 전)을 넘으면 오류가 난다.
- 모듈 방식(`dt.datetime.now`) 읽기와 `time.time()` 은 바꾸지 못한다(앞의 것은 시험이 금지한다).
"""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
REFERENCE_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=KST)  # 화요일 낮 12시(한국 시간)
TICK = timedelta(milliseconds=1)
_active = False
_reference: datetime | None = None


def reference_now() -> datetime | None:
    """열려 있는 고정 시계의 기준 시각(없으면 None). 시드가 기준 날짜가 맞는지 확인할 때 쓴다."""
    return _reference


def is_frozen() -> bool:
    """고정 시계가 열려 있는가(시드는 날짜가 고정된 안에서만 만든다)."""
    return _active


def _midnight_after(now: datetime) -> datetime:
    local = now.astimezone(KST)
    return datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=KST)


def make_clock(now: datetime) -> tuple[type[datetime], type[date]]:
    """`now` 에서 시작하는 (datetime 대신 쓸 클래스, date 대신 쓸 클래스)."""
    if now.tzinfo is None:
        raise ValueError("기준 시각에는 시간대가 있어야 한다")
    start = now.astimezone(UTC)
    max_ticks = int((_midnight_after(start) - start) / TICK) - 1  # 한국 시간 자정 전까지
    state = {"now": start, "ticks": 0}

    def advance() -> datetime:
        state["ticks"] += 1
        if state["ticks"] > max_ticks:
            raise RuntimeError(
                "고정 시계가 기준 날짜의 한국 시간 자정을 넘어 흘렀다(날짜가 바뀐다)"
            )
        state["now"] += TICK
        return state["now"]

    def local_naive() -> datetime:  # 시간대를 주지 않은 now()/today() 는 현지(한국) 시각
        return advance().astimezone(KST).replace(tzinfo=None)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102
            return advance().astimezone(tz) if tz is not None else local_naive()

        @classmethod
        def today(cls):  # noqa: D102
            return local_naive()

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
    global _active, _reference
    if _active:
        raise RuntimeError("고정 시계는 겹쳐 열 수 없다")
    import app.main  # noqa: F401  모든 기능 모듈을 먼저 불러온다(켠 뒤에 처음 불러오는 모듈이 실제 시각을 읽지 않게)

    fake_datetime, fake_date = make_clock(now)
    patched: list[tuple[object, str, object]] = []
    known = set(sys.modules)
    for name, module in list(sys.modules.items()):
        if not name.startswith(prefix) or module is None:
            continue
        for attr, fake, real in (("datetime", fake_datetime, datetime), ("date", fake_date, date)):
            if getattr(module, attr, None) is real:
                patched.append((module, attr, real))
                setattr(module, attr, fake)
    _active = True
    _reference = now
    try:
        yield
        late = sorted(
            n
            for n, m in sys.modules.items()
            if n.startswith(prefix)
            and n not in known
            and m is not None
            and (getattr(m, "datetime", None) is datetime or getattr(m, "date", None) is date)
        )
        if late:
            raise RuntimeError(f"시계를 켠 뒤에 불러온 모듈이 실제 시각을 읽는다: {late}")
    finally:
        _active = False
        _reference = None
        for module, attr, real in patched:
            setattr(module, attr, real)
