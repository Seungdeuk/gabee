"""비용 계산, 예산 범위, 호출별 사용량 기록. 네트워크·LLM·DB 를 쓰지 않는 순수 계산이다.

## 단가
Anthropic API 1차 단가(`PRICES`)로 계산한다. 단가를 모르는 모델은 추정하지 않고 거부한다.
캐시 할인·배치 할인은 반영하지 않는다(실제보다 비싸게 계산하는 보수적 방향).

## 예산 범위(`Scope`)와 적용 기준
지출은 아래 범위에 각각 합산되고, 한 범위라도 상한을 넘으면 `BudgetExceeded` 로 멈춘다.

| 범위 | 상한 | 합산 대상 | 시작 |
|---|---|---|---|
| RUN | $2 | 실행기를 한 번 부르는 동안의 지출 | 실행마다 0 |
| BASELINE | $5 | 1단계 베이스라인의 4번 실행 전체 | 첫 실행 0, 이후 이전 실행의 합 |
| LOOP | $15 | 루프 한 번(재평가 실행과 후보를 만드는 호출) | 루프마다 0 |
| PROJECT | $40 | 프로젝트 시작부터 모든 지출 | 지금까지의 합 |

어떤 지출이 어느 범위에 들어가는지는 `*_SCOPES` 상수가 정한다(예: 베이스라인 실행은 RUN·BASELINE·
PROJECT, 루프 안의 재평가 실행은 RUN·LOOP·PROJECT, 후보를 만드는 호출은 LOOP·PROJECT).
BASELINE·LOOP·PROJECT 의 '지금까지의 합'은 호출하는 쪽이 이전 실행 기록(manifest)에서 읽어 `opening` 으로 넘긴다.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

PRICE_SOURCE = (
    "Anthropic API 1차 단가(claude-api 모델 표, 2026-11-03 기준, 1M 토큰당 USD). "
    "Haiku 5.5 는 입력이 100K 토큰을 넘는 요청에 장문 단가. 캐시·배치 할인은 반영하지 않음."
)


@dataclass(frozen=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    long_input_per_mtok: Decimal | None = None  # 입력이 long_threshold 를 넘는 요청의 단가
    long_output_per_mtok: Decimal | None = None
    long_threshold: int | None = None


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(
        Decimal("0.10"), Decimal("0.50"), Decimal("0.50"), Decimal("2.50"), 100_000
    ),
    "claude-sonnet-5-5": Price(Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": Price(Decimal("4.00"), Decimal("20.00")),
}
_MTOK = Decimal(1_000_000)


def _price(model: str) -> Price:
    if model not in PRICES:
        raise ValueError(f"단가를 모르는 모델이다(추정하지 않는다): {model}")
    return PRICES[model]


def call_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """모델 호출 한 번의 비용(USD)."""
    if tokens_in < 0 or tokens_out < 0:
        raise ValueError("토큰 수는 0 이상이어야 한다")
    p = _price(model)
    long = p.long_threshold is not None and tokens_in > p.long_threshold
    in_price = p.long_input_per_mtok if long else p.input_per_mtok
    out_price = p.long_output_per_mtok if long else p.output_per_mtok
    return (Decimal(tokens_in) * in_price + Decimal(tokens_out) * out_price) / _MTOK


def token_cap_for(budget: Decimal, model: str) -> int:
    """예산을 토큰 상한으로 바꾼다. 입출력 비율을 모르는 동안은 전부 가장 비싼 출력 단가(장문 단가 포함)로
    계산해(보수적) 낮게 잡는다."""
    p = _price(model)
    return int(budget / max(p.output_per_mtok, p.long_output_per_mtok or 0) * _MTOK)


def estimate_cost(
    model: str, queries: int, tokens_in_per_query: int, tokens_out_per_query: int
) -> Decimal:
    """질의 수와 질의당 토큰(가정값, 호출하는 쪽이 정한다)으로 실행 전에 비용을 추정한다."""
    return queries * call_cost(model, tokens_in_per_query, tokens_out_per_query)


class Scope(StrEnum):
    RUN = "run"
    BASELINE = "baseline"
    LOOP = "loop"
    PROJECT = "project"


CAPS: dict[Scope, Decimal] = {
    Scope.RUN: Decimal("2"),
    Scope.BASELINE: Decimal("5"),
    Scope.LOOP: Decimal("15"),
    Scope.PROJECT: Decimal("40"),
}
BASELINE_RUN_SCOPES = (Scope.RUN, Scope.BASELINE, Scope.PROJECT)  # 1단계 베이스라인의 실행
LOOP_RUN_SCOPES = (Scope.RUN, Scope.LOOP, Scope.PROJECT)  # 루프 안의 재평가 실행
LOOP_CALL_SCOPES = (Scope.LOOP, Scope.PROJECT)  # 루프에서 후보를 만드는 호출
OTHER_RUN_SCOPES = (Scope.RUN, Scope.PROJECT)  # 시험 실행, 최종 평가 등


class BudgetExceeded(Exception):
    def __init__(self, scope: Scope, spent: Decimal, cap: Decimal) -> None:
        super().__init__(f"예산 초과: {scope.value} 범위 {spent} USD > 상한 {cap} USD")
        self.scope, self.spent, self.cap = scope, spent, cap


@dataclass(frozen=True)
class CallUsage:
    """모델 호출 하나의 사용량. 내용(질문·답)은 담지 않는다."""

    case_id: str
    repeat: int
    call_index: int
    model: str
    tokens_in: int
    tokens_out: int
    cost: Decimal
    cumulative: Decimal  # 이 기록장에서 지금까지의 합

    def as_dict(self) -> dict[str, int | str]:
        return {
            "case_id": self.case_id,
            "repeat": self.repeat,
            "call_index": self.call_index,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": format(self.cost, "f"),
            "cumulative_usd": format(self.cumulative, "f"),
        }


class Ledger:
    """호출별 사용량과 누적 비용을 기록하고, 적용 범위의 상한을 지킨다."""

    def __init__(
        self,
        scopes: Sequence[Scope],
        opening: Mapping[Scope, Decimal] | None = None,
        caps: Mapping[Scope, Decimal] = CAPS,
    ) -> None:
        self.scopes = tuple(scopes)
        self._caps = caps
        self.spent: dict[Scope, Decimal] = {s: Decimal(0) for s in self.scopes}
        for scope, amount in (opening or {}).items():
            if scope in self.spent:
                self.spent[scope] += amount
        self.usages: list[CallUsage] = []
        self.total = Decimal(0)  # 이 기록장이 직접 쓴 합(opening 제외)
        self._counts: Counter[tuple[str, int]] = Counter()

    def _over(self, extra: Decimal) -> Scope | None:
        return next((s for s in self.scopes if self.spent[s] + extra > self._caps[s]), None)

    def check_estimate(self, estimate: Decimal) -> None:
        """시작하기 전에 추정 비용이 어느 범위의 상한이라도 넘기면 막는다."""
        scope = self._over(estimate)
        if scope is not None:
            raise BudgetExceeded(scope, self.spent[scope] + estimate, self._caps[scope])

    def remaining(self) -> dict[Scope, Decimal]:
        return {s: self._caps[s] - self.spent[s] for s in self.scopes}

    def record(
        self, case_id: str, repeat: int, model: str, tokens_in: int, tokens_out: int
    ) -> CallUsage:
        """호출 하나를 기록한다. 기록한 뒤 상한을 넘었으면 `BudgetExceeded` 로 남은 호출을 멈추게 한다."""
        cost = call_cost(model, tokens_in, tokens_out)
        for scope in self.scopes:
            self.spent[scope] += cost
        self.total += cost
        index = self._counts[(case_id, repeat)]
        self._counts[(case_id, repeat)] += 1
        usage = CallUsage(case_id, repeat, index, model, tokens_in, tokens_out, cost, self.total)
        self.usages.append(usage)
        scope = self._over(Decimal(0))
        if scope is not None:
            raise BudgetExceeded(scope, self.spent[scope], self._caps[scope])
        return usage
