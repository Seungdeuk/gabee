"""가비 추천을 사용자마다 다르게 보이게 하는 공통 선택. 가족이 같은 추천 목록(가족 단위 캐시)을 갖고 있어도
사람마다 그중 일부만 보여 줘서, 한 사람이 낸 문제의 답을 다른 가족이 미리 보지 않게 한다."""

import hashlib
from datetime import date


def show_count(total: int) -> int:
    """후보가 total 개일 때 한 사람에게 보여 주는 개수: 절반 올림(1→1, 2→1, 3→2, 4→2, 5→3, 7→4)."""
    return (total + 1) // 2


def pick_for_user(items: list[dict], group_id: str, user_id: str, today: date) -> list[dict]:
    """가족·사용자·날짜와 항목 `id` 로 정한 해시 순서에서 앞의 절반(올림)만 골라 원래 순서로 돌려준다.
    같은 사용자의 같은 날은 항상 같고, 후보가 하나 늘거나 줄어도 나머지의 상대 순서는 그대로다. 입력은 바꾸지 않는다."""
    salt = f"{group_id}|{user_id}|{today.isoformat()}"

    def order(item: dict) -> str:
        return hashlib.sha256(f"{salt}|{item['id']}".encode()).hexdigest()

    chosen = {id(x) for x in sorted(items, key=order)[: show_count(len(items))]}
    return [x for x in items if id(x) in chosen]
