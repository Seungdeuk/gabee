"""실행 전 비용 추정을 만들어 예산 상한을 확인하고, 사람이 읽을 요약을 돌려준다. LLM 은 부르지 않는다.

토큰 수는 가정값이라 호출하는 쪽이 정한다(질문 하나가 모델을 최대 몇 번 부르는지, 호출당 토큰). 추정이 어느 범위의 상한이라도
넘으면 `cost.BudgetExceeded` 로 시작하기 전에 멈춘다. 이 요약을 사용자에게 보여 주고 승인을 받은 뒤에만 실제 호출을 한다.
"""

from decimal import Decimal

from .cost import PRICE_SOURCE, Ledger, estimate_cost


def build_estimate(
    ledger: Ledger,
    model: str,
    cases: int,
    repeats: int,
    calls_per_case: int,
    tokens_in_per_call: int,
    tokens_out_per_call: int,
) -> tuple[Decimal, str]:
    """(추정 비용 USD, 출력할 요약). 상한을 넘으면 `BudgetExceeded`."""
    if min(cases, repeats, calls_per_case) < 1:
        raise ValueError("사례·반복·사례당 호출 수는 1 이상이어야 한다")
    queries = cases * repeats * calls_per_case
    total = estimate_cost(model, queries, tokens_in_per_call, tokens_out_per_call)
    ledger.check_estimate(total)
    remaining = {s.value: format(v, "f") for s, v in ledger.remaining().items()}
    summary = "\n".join(
        [
            f"[비용 추정] 모델 {model}, 사례 {cases} x 반복 {repeats} x 사례당 최대 {calls_per_case}회 = 호출 {queries}회",
            f"  가정: 호출당 입력 {tokens_in_per_call} / 출력 {tokens_out_per_call} 토큰",
            f"  추정 비용: {format(total, 'f')} USD, 남은 예산: {remaining}",
            f"  단가: {PRICE_SOURCE}",
            "  실제 호출은 이 추정을 보여 주고 승인을 받은 뒤에만 한다.",
        ]
    )
    return total, summary
