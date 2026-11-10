"""공유 카드(`message_shares.payload`)를 AI 가 읽을 한 줄 글로 바꾼다. 순수 함수라 DB·네트워크를 쓰지 않는다.

카드 메시지의 글자(messages.text)는 개인정보 없는 고정 문구라서, AI 로 읽을 때(@가비 맥락·대화 분석)만 이 요약으로 바꿔 넣는다.
발화자 이름은 대화 줄 앞에 이미 붙으므로 글에 넣지 않는다. 이 글도 일반 메시지처럼 가명화(`prepare_transcript`)를 거쳐 나간다.
payload 는 서버가 만든 값이지만 옛 버전·깨진 값이 있어도 예외를 내지 않고, 만들 수 없으면 고정 문구로 돌아간다."""

from typing import Any

from app.shared import chat_share

MAX_CHARS = 400  # 요약 글 길이 상한(제목·장소가 길어도 AI 맥락이 커지지 않게)
_KIND_TODO = 2  # 일정 카드의 kind: 1 약속, 2 할 일
_GENERIC = "카드를 공유했어요"  # 모르는 kind 의 고정 문구


def card_text(kind: str, payload: Any) -> str:
    """카드 kind(event | settlement)와 payload 로 AI 가 읽을 한 줄을 만든다. 만들 수 없으면 그 kind 의 고정 문구."""
    fixed = chat_share.SUMMARY_TEXT.get(kind, _GENERIC)
    if not isinstance(payload, dict):
        return fixed
    try:
        if kind == chat_share.EVENT:
            text = _event(payload)
        elif kind == chat_share.SETTLEMENT:
            text = _settlement(payload)
        else:
            text = None
    except (TypeError, ValueError, AttributeError):  # 깨진 값은 고정 문구로
        text = None
    return _clip(text) if text else fixed


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 1] + "…"


def _clean(value: Any) -> str:
    """글자가 아니면 빈 값. 줄바꿈·겹친 공백은 한 칸으로(AI 줄이 한 줄로 유지되게)."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _day(value: Any) -> str:
    """'YYYY-MM-DD' → 'MM/DD'. 없거나 모양이 다르면 '날짜 미정'."""
    parts = _clean(value).split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[1]}/{parts[2]}"
    return "날짜 미정"


def _hhmm(value: Any) -> str:
    text = _clean(value)
    return text if len(text) == 5 and text[2] == ":" else ""


def _event(payload: dict) -> str | None:
    title = _clean(payload.get("title"))
    if not title:
        return None
    label = "할 일 공유" if payload.get("kind") == _KIND_TODO else "일정 공유"
    start, end = _hhmm(payload.get("start_time")), _hhmm(payload.get("end_time"))
    when = _day(payload.get("date"))
    if start and end:
        when += f" {start}~{end}"
    elif start:
        when += f" {start}"
    names = payload.get("with_names")
    with_names = [n for n in (_clean(x) for x in names) if n] if isinstance(names, list) else []
    parts = [f"[{label}] {title}", when]
    if place := _clean(payload.get("place")):
        parts.append(place)
    if with_names:
        parts.append("함께: " + ", ".join(with_names))
    return " · ".join(parts)


def _settlement(payload: dict) -> str | None:
    remaining = _int(payload.get("remaining"))
    if remaining is None:
        return None
    month = _clean(payload.get("month"))
    head = f"[정산 공유 {month}]" if month else "[정산 공유]"
    if remaining > 0:
        total = f"받을 돈 {_won(remaining)}"
    elif remaining < 0:
        total = f"보낼 돈 {_won(-remaining)}"
    else:
        total = "정산할 돈 없음"
    parts = [f"{head} {total}"]
    lines = payload.get("lines")
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        name, amount = _clean(line.get("name")), _int(line.get("amount"))
        direction = line.get("direction")
        if not name or amount is None or direction not in ("send", "receive"):
            continue
        parts.append(
            f"{name}에게 {_won(amount)} " + ("보낼 돈" if direction == "send" else "받을 돈")
        )
    return " · ".join(parts)
