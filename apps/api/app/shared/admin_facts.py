"""관리자 챗봇 에이전트가 쓸 도구 명단.

각 기능이 자기 폴더의 admin_facts.py 에서 register() 로 숫자 함수를 올리고,
챗봇(admin_knowledge)은 이 명단을 도구로 넘겨 Claude 가 필요한 것을 고르게 한다.
그래서 챗봇이 다른 기능의 내부 함수를 직접 부르지 않고, 명단에 없는 조회는 할 수 없다.

숫자 함수가 돌려준 글은 외부(Claude)로 나간다. 읽기 전용으로 만들고, 개수·비율·오류 종류만 담고,
이름·이메일·사용자 id·오류 message·trace id 는 넣지 않는다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, Field

FactReader = Callable[..., list[str]]  # (db) 또는 (db, **입력칸)

# 날짜 기간 도구가 한 번에 돌려주는 최대 일수(Claude 로 가는 글 길이·비용을 막는다)
MAX_RANGE_DAYS = 90


class DateRange(BaseModel):
    """날짜 기간 입력칸. 둘 다 비우면 도구의 기본 기간을 쓴다. 값은 Claude 가 질문을 보고 채운다."""

    start: str | None = Field(
        default=None, description="시작 날짜 YYYY-MM-DD(한국 시간, 포함). 비우면 기본 기간"
    )
    end: str | None = Field(
        default=None, description="끝 날짜 YYYY-MM-DD(한국 시간, 포함). 비우면 오늘"
    )


def parse_range(
    start: str | None, end: str | None, today: date, default_days: int
) -> tuple[date, date] | str:
    """입력칸을 (첫날, 끝날)로 바꾼다. 잘못된 값이면 Claude 에게 돌려줄 안내 글을 돌려준다.
    Claude 가 채운 값이라 그대로 믿지 않고 여기서 다시 검사한다."""
    try:
        last = date.fromisoformat(end) if end else today
        first = date.fromisoformat(start) if start else last - timedelta(days=default_days - 1)
    except ValueError:
        return "날짜는 YYYY-MM-DD 모양으로 주세요(예: 2026-10-03)."
    if first > last:
        return "시작 날짜가 끝 날짜보다 늦어요."
    if last > today:
        return f"오늘({today})보다 뒤의 날짜는 셀 수 없어요."
    if (last - first).days + 1 > MAX_RANGE_DAYS:
        return f"한 번에 최대 {MAX_RANGE_DAYS}일까지 볼 수 있어요. 기간을 나눠서 물어 주세요."
    return first, last


@dataclass(frozen=True)
class Fact:
    name: str  # 도구 이름(영문·숫자·밑줄만 된다)
    description: str  # Claude 가 읽고 고른다. 무엇을 주는지, 언제 쓰는지 쓴다
    read: FactReader
    order: int  # 작은 수가 먼저 나온다
    params: type[BaseModel] | None = None  # 입력칸(없으면 입력 없는 도구). 있으면 read(db, **입력)
    label: str = ""  # 관리자 화면의 답변 단계에 보이는 짧은 말(예: "회원 수 확인"). 비우면 name


_FACTS: dict[str, Fact] = {}


def register(
    name: str,
    description: str,
    read: FactReader,
    *,
    order: int,
    params: type[BaseModel] | None = None,
    label: str = "",
) -> None:
    """같은 이름으로 다시 올리면 바꾼다(모듈을 다시 읽어도 두 번 들어가지 않는다)."""
    _FACTS[name] = Fact(name, description, read, order, params, label or name)


def all_facts() -> list[Fact]:
    return sorted(_FACTS.values(), key=lambda f: f.order)
