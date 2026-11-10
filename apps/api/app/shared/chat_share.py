"""채팅방 공유 카드의 내용을 만드는 통로. 일정·정산처럼 다른 기능의 데이터를 family_chat 이 직접 읽지 않도록,
데이터 주인 기능(schedule·billing)이 시작할 때 **카드 내용을 만드는 함수**를 여기에 등록하고, family_chat 은 `build` 만 부른다
(`shared/room_assistant.py`·`shared/chat_library.py` 와 같은 방향).

- 내용은 **서버가 직접 읽어서** 만든다. 클라이언트가 보낸 제목·금액은 받지 않는다(위조 방지). 만드는 함수는 "내가 포함된 것인지"를
  자기 기능 안에서 확인하고, 아니면 404 를 낸다(존재 여부를 숨긴다).
- 만드는 함수가 등록돼 있지 않으면(`build` → 503) 보내지 않는다. 카드 내용을 만들 수 없는데 빈 카드를 올리면 안 된다.
- 카드 글자(`text`)는 개인정보 없는 고정 문구다(`SUMMARY_TEXT`). 금액·제목은 `payload` 에만 있다."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.shared.errors import ApiError
from app.shared.rate_limit import FailureLimiter

EVENT = "event"
SETTLEMENT = "settlement"
KINDS = (EVENT, SETTLEMENT)

# 채팅 메시지 글자로 저장되는 고정 문구(구버전 앱·방 목록 미리보기·답장 인용에 그대로 보인다)
SUMMARY_TEXT = {EVENT: "일정을 공유했어요", SETTLEMENT: "정산을 공유했어요"}

MAX_PAYLOAD_BYTES = 4096  # 카드 하나의 내용 크기 상한(JSON 글자 기준)

# (db, group_id, user_id, ref, peer_id) → payload. peer_id 는 1:1 방이면 상대, 가족 전체방이면 None.
Provider = Callable[[Session, str, str, str, str | None], dict[str, Any]]
_providers: dict[str, Provider] = {}

limiter = FailureLimiter()  # 프로세스 메모리(사진·파일과 따로 센다)


def register_provider(kind: str, fn: Provider) -> None:
    """kind 의 카드 내용을 만드는 함수를 등록한다(schedule·billing 이 시작할 때 부른다)."""
    _providers[kind] = fn


def build(
    db: Session, kind: str, group_id: str, user_id: str, ref: str, peer_id: str | None
) -> dict[str, Any]:
    """카드 내용(payload)을 서버에서 만든다. group_id·user_id 는 호출한 쪽이 실제 구성원인지 확인한 값이어야 한다.
    만드는 함수가 없으면 503, 내가 포함된 것이 아니거나 없으면 404(만드는 함수가 낸다)."""
    provider = _providers.get(kind)
    if provider is None:
        raise ApiError(503, "share_unavailable", "지금은 공유할 수 없어요. 잠시 후 다시 해 주세요")
    return provider(db, group_id, user_id, ref, peer_id)
