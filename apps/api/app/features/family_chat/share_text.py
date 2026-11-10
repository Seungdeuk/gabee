"""공유 카드(`message_shares.payload`)를 AI 가 읽을 한 줄 글로 바꾼다. 순수 함수라 DB·네트워크를 쓰지 않는다.

카드 메시지의 글자(messages.text)는 개인정보 없는 고정 문구라서, AI 로 읽을 때(@가비 맥락·대화 분석)만 이 요약으로 바꿔 넣는다.
발화자 이름은 대화 줄 앞에 이미 붙으므로 글에 넣지 않는다. 이 글도 일반 메시지처럼 가명화(`prepare_transcript`)를 거쳐 나간다.
카드에 든 이름(`card_names`)은 **보낸 시점에 찍힌 값**이라 지금 구성원이 아닌 사람(나간 사람)의 이름일 수 있으므로,
부르는 쪽이 가명화 이름 사전에 더해야 한다. 돈의 방향은 카드를 올린 사람 기준이라 글에 "공유한 사람"을 주어로 쓴다.
payload 는 서버가 만든 값이지만 옛 버전·깨진 값이 있어도 예외를 내지 않고, 만들 수 없으면 고정 문구로 돌아간다."""

from typing import Any

from app.shared import chat_share

MAX_CHARS = 400  # 요약 글 길이 상한(제목·장소가 길어도 AI 맥락이 커지지 않게)
_SEP = " · "
_MORE = " …"  # 상한 때문에 뒤 항목을 뺐다는 표시
_KIND_TODO = 2  # 일정 카드의 kind: 1 약속, 2 할 일
_GENERIC = "카드를 공유했어요"  # 모르는 kind 의 고정 문구


def card_text(kind: str, payload: Any) -> str:
    """카드 kind(event | settlement)와 payload 로 AI 가 읽을 한 줄을 만든다. 만들 수 없으면 그 kind 의 고정 문구."""
    fixed = chat_share.SUMMARY_TEXT.get(kind, _GENERIC)
    if not isinstance(payload, dict):
        return fixed
    try:
        if kind == chat_share.EVENT:
            items = _event(payload)
        elif kind == chat_share.SETTLEMENT:
            items = _settlement(payload)
        else:
            items = None
    except (TypeError, ValueError, AttributeError):  # 깨진 값은 고정 문구로
        items = None
    return _join(items) if items else fixed


def card_names(kind: str, payload: Any) -> list[str]:
    """카드에 든 사람 이름(같이하는 사람·정산 상대). 가명화 이름 사전에 더하려고 쓴다(중복 없이, 깨진 값은 건너뜀)."""
    if not isinstance(payload, dict):
        return []
    try:
        if kind == chat_share.EVENT:
            raw = payload.get("with_names")
            names = [_clean(x) for x in raw] if isinstance(raw, list) else []
        elif kind == chat_share.SETTLEMENT:
            raw = payload.get("lines")
            names = (
                [_clean(x.get("name")) for x in raw if isinstance(x, dict)]
                if isinstance(raw, list)
                else []
            )
        else:
            names = []
    except (TypeError, ValueError, AttributeError):
        names = []
    return list(dict.fromkeys(n for n in names if n))


def _join(items: list[str]) -> str:
    """항목(제목·날짜·장소·함께·줄) 단위로 이어 붙이고, 상한을 넘으면 뒤 항목을 통째로 뺀 뒤 … 를 붙인다.
    첫 항목(제목)이 혼자 상한을 넘으면 그것만 자르고 나머지는 뺀다. 이름·줄 중간에서 자르지 않는다."""
    text = _SEP.join(items)
    if len(text) <= MAX_CHARS:
        return text
    if len(items[0]) + len(_MORE) > MAX_CHARS:
        return items[0][: MAX_CHARS - 1] + "…"
    kept = [items[0]]
    for item in items[1:]:
        if len(_SEP.join([*kept, item])) + len(_MORE) > MAX_CHARS:
            break
        kept.append(item)
    return _SEP.join(kept) + _MORE


def _clean(value: Any) -> str:
    """글자가 아니면 빈 값. 줄바꿈·겹친 공백은 한 칸으로(AI 줄이 한 줄로 유지되게)."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _won(amount: int) -> str:
    return f"{amount:,}원"


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _day(value: Any) -> str:
    """'YYYY-MM-DD' 그대로(연도 포함). 없거나 모양이 다르면 '날짜 미정'."""
    text = _clean(value)
    parts = text.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return text
    return "날짜 미정"


def _hhmm(value: Any) -> str:
    text = _clean(value)
    return text if len(text) == 5 and text[2] == ":" else ""


def _event(payload: dict) -> list[str] | None:
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
    items = [f"[{label}] {title}", when]
    if place := _clean(payload.get("place")):
        items.append(place)
    if names := card_names(chat_share.EVENT, payload):
        items.append("함께: " + ", ".join(names))
    return items


def _settlement(payload: dict) -> list[str] | None:
    remaining = _int(payload.get("remaining"))
    if remaining is None:
        return None
    month = _clean(payload.get("month"))
    head = f"[정산 공유 {month}]" if month else "[정산 공유]"
    # 금액·방향은 카드를 올린 사람 기준이다: 읽는 AI 가 요청한 사람 입장으로 거꾸로 이해하지 않게 주어를 쓴다
    if remaining > 0:
        total = f"공유한 사람이 받을 돈 {_won(remaining)}"
    elif remaining < 0:
        total = f"공유한 사람이 보낼 돈 {_won(-remaining)}"
    else:
        total = "공유한 사람은 정산할 돈 없음"
    items = [f"{head} {total}"]
    lines = payload.get("lines")
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        name, amount = _clean(line.get("name")), _int(line.get("amount"))
        direction = line.get("direction")
        if not name or amount is None or direction not in ("send", "receive"):
            continue
        if direction == "send":
            items.append(f"{name}에게 {_won(amount)} 보낼 돈")
        else:
            items.append(f"{name}에게서 {_won(amount)} 받을 돈")
    return items
