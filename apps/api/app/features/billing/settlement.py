"""정산 계산. DB 를 모르는 순수 함수만 둔다(금액은 정수 원)."""


def split_equally(amount: int, user_ids: list[str]) -> dict[str, int]:
    """나눌 사람 순서대로 나누고, 나머지 원은 앞 사람부터 1원씩 더한다."""
    base, rest = divmod(amount, len(user_ids))
    return {uid: base + (1 if i < rest else 0) for i, uid in enumerate(user_ids)}


def minimal_transfers(balances: dict[str, int]) -> list[tuple[str, str, int]]:
    """잔액(양수=받을 돈, 음수=낼 돈, 합계 0)을 (보내는 사람, 받는 사람, 금액) 으로 줄인다.
    가장 많이 낼 사람이 가장 많이 받을 사람에게 보내는 것을 반복한다. 송금 횟수는 최대 (사람 수 - 1)번이다.
    금액이 같으면 balances 에 들어 있는 순서가 앞선 사람이 먼저다."""
    debtors = [[uid, -b] for uid, b in balances.items() if b < 0]
    creditors = [[uid, b] for uid, b in balances.items() if b > 0]
    result: list[tuple[str, str, int]] = []
    while debtors and creditors:
        debtors.sort(key=lambda x: -x[1])  # sort 는 안정 정렬이라 동률이면 입력 순서가 유지된다
        creditors.sort(key=lambda x: -x[1])
        pay = min(debtors[0][1], creditors[0][1])
        result.append((debtors[0][0], creditors[0][0], pay))
        debtors[0][1] -= pay
        creditors[0][1] -= pay
        debtors = [d for d in debtors if d[1] > 0]
        creditors = [c for c in creditors if c[1] > 0]
    return result
