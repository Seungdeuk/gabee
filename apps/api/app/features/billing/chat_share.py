"""채팅방 공유 카드의 정산 내용을 만든다(`shared/chat_share.py` 에 등록, router 가 import 하면 등록된다).

그 달(ref = YYYY-MM)의 **내 몫만** 담는다: 내 남은 잔액(받을 돈은 +, 보낼 돈은 −)과, 내가 보내거나 받을 송금 줄(상대 이름·금액).
남들끼리 주고받는 줄은 담지 않는다. 1:1 방에서는 그 상대와 주고받는 줄만 담는다. 정산하기를 마친 지출만 계산에 들어가므로
(`service.settlement`) 정산 내역에 내가 없으면 404 다. 읽은 값을 그 자리에서 복사한 것이라 나중에 정산이 바뀌어도 카드는 그대로다."""

from typing import Any

from sqlalchemy.orm import Session

from app.shared import chat_share
from app.shared.errors import not_found

from . import service


def settlement_card(
    db: Session, group_id: str, user_id: str, ref: str, peer_id: str | None
) -> dict[str, Any]:
    month = service.check_month(ref)  # 형식이 틀리면 400
    result = service.settlement(db, group_id, month)
    mine = next((b for b in result.balances if b.user_id == user_id), None)
    if mine is None or (
        mine.paid == 0 and mine.share == 0
    ):  # 그 달 정산에 내가 낸 것도 나눌 몫도 없다
        raise not_found("정산")
    lines = []
    for t in result.transfers:
        if t.from_user_id == user_id:
            direction, other_id, other_name = "send", t.to_user_id, t.to_name
        elif t.to_user_id == user_id:
            direction, other_id, other_name = "receive", t.from_user_id, t.from_name
        else:
            continue  # 남들끼리의 송금은 담지 않는다
        if peer_id is not None and other_id != peer_id:
            continue  # 1:1 방이면 그 상대와의 줄만
        lines.append({"direction": direction, "name": other_name, "amount": t.amount})
    # 가족방 카드는 내 전체 남은 잔액, 1:1 카드는 그 상대와의 줄 합계(카드 안에서 줄과 앞뒤가 맞고 제3자와의 관계를 드러내지 않는다)
    remaining = (
        sum(x["amount"] if x["direction"] == "receive" else -x["amount"] for x in lines)
        if peer_id is not None
        else mine.remaining
    )
    return {"month": month, "remaining": remaining, "lines": lines}


chat_share.register_provider(chat_share.SETTLEMENT, settlement_card)
