"""일정 추천(먼저 권해드려요)이 일정 말고 더 읽는 입력 출처. 추천 한 번의 모델 호출에 줄 단위 요약으로 함께 보낸다.

- 부탁(함께하기): 내가 보낸 부탁과 아직 답하지 않은 받은 부탁. 이미 있는 부탁에서 파생되는 할 일(예약 확인, 준비물)을 제안하는 근거다.
- 가계: 내가 결제하는 구독(OTT·통신비)의 다음 결제일. 서비스 이름과 날짜만 보내고 금액·지출 내역은 읽지 않는다.
- 가족 소통: 소통 에이전트의 대화 분석 결과(일정·할 일 후보)를 재사용한다. 원문 대화는 보내지 않는다. 분석을 못 쓰면(동의·한도·AI 오류) 이 출처만 비운다.
- 개인 채팅: 앱이 요청에 실어 보낸 최근 7일 안의 내 말. 서버는 저장하지 않고 개인정보를 가려서 쓴다.
출처마다 기간·개수 상한이 있고, 어느 하나가 비거나 실패해도 추천 자체는 계속된다. 돌봄은 읽지 않는다."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

# ai_assistant 기능 폴더의 mask_text: 여러 줄 텍스트에서 주민번호·전화·카드·이메일·계좌·주소 등을 가린다(chat.py 와 같다).
from app.features.ai_assistant.ingest.masking import mask_text
from app.features.billing import allowance
from app.features.billing import repository as billing_repo
from app.features.family_chat import ai_service
from app.features.family_chat.ai_schemas import RangeIn
from app.features.family_group.models import User
from app.features.schedule import together
from app.shared.errors import ApiError

from .prompts import WEEKDAYS

AHEAD_DAYS = 60  # 추천 날짜 범위와 같다
PAST_DAYS = 14
MAX_REQUEST_LINES = 20
MAX_BILLING_LINES = 12
MAX_FAMILY_LINES = 20
MAX_CHAT_LINES = 30
MAX_CHAT_CHARS = 200
SUBSCRIPTION_KIND = {"ott": "OTT", "telecom": "통신비"}


@dataclass
class Sources:
    requests: list[str] = field(default_factory=list)
    billing: list[str] = field(default_factory=list)
    family: list[str] = field(default_factory=list)
    chat: list[str] = field(default_factory=list)


def _day(value: date) -> str:
    return f"{value:%Y-%m-%d}({WEEKDAYS[value.weekday()]})"


def request_lines(db: Session, group_id: str, user_id: str, today: date) -> list[str]:
    """내가 보낸 부탁(취소 제외)과 아직 답하지 않은 받은 부탁. 날짜는 지난 2주~앞으로 60일."""
    since, until = today - timedelta(days=PAST_DAYS), today + timedelta(days=AHEAD_DAYS)
    out: list[tuple[date, str]] = []
    for row in together.list_mine(db, group_id, user_id):
        if row["canceled"] or not since <= row["start_date"] <= until:
            continue
        if row["from_id"] == user_id:
            label = "내가 보낸 부탁"
        else:
            mine = next((r["status"] for r in row["recipients"] if r["user_id"] == user_id), "")
            if (
                mine != "waiting"
            ):  # 수락한 부탁은 이미 내 일정에 있고, 어렵다고 한 부탁은 제안 근거가 아니다
                continue
            label = "받은 부탁(답 전)"
        start = row["start_time"]
        clock = f" {start:%H:%M}" if start else ""
        out.append(
            (
                row["start_date"],
                f"{_day(row['start_date'])}{clock} | {mask_text(row['title'])} | {label}",
            )
        )
    out.sort(key=lambda x: x[0])
    return [line for _, line in out[:MAX_REQUEST_LINES]]


def billing_lines(db: Session, group_id: str, user_id: str, today: date) -> list[str]:
    """내가 결제하는 구독의 앞으로 60일 안 결제일. 이름과 날짜만(금액은 보내지 않는다)."""
    until = today + timedelta(days=AHEAD_DAYS)
    out: list[tuple[date, str]] = []
    for item in billing_repo.list_subscriptions(db, group_id):
        if getattr(item, "payer_id", None) != user_id or item.billing_day is None:
            continue
        due = allowance.next_due("monthly", item.billing_day, today)
        while due <= until:
            kind = SUBSCRIPTION_KIND.get(item.kind, "구독")
            out.append((due, f"{_day(due)} | {mask_text(item.name)} 결제일({kind})"))
            due = allowance.next_due("monthly", item.billing_day, due + timedelta(days=1))
    out.sort(key=lambda x: x[0])
    return [line for _, line in out[:MAX_BILLING_LINES]]


def family_lines(db: Session, user_id: str, group_id: str, today: date) -> list[str]:
    """가족 전체방 대화 분석의 일정·할 일 후보. 분석을 못 쓰면 빈 목록(추천은 계속)."""
    user = db.get(User, user_id)
    if user is None:
        return []
    try:
        analysis = ai_service.analysis(db, user, group_id, RangeIn())
    except ApiError:
        return []
    out: list[str] = []
    for c in analysis.schedule_candidates:
        when = " ".join(x for x in (c.date, c.time) if x) or "날짜 미정"
        place = f" @{mask_text(c.place)}" if c.place else ""
        out.append(f"{when} | {mask_text(c.title)}{place} | 일정 후보")
    for t in analysis.todo_candidates:
        out.append(f"{t.due or '기한 미정'} | {mask_text(t.title)} | 할 일 후보")
    return out[:MAX_FAMILY_LINES]


def clean_chat(chat: list[str] | None) -> list[str]:
    """앱이 보낸 내 말을 다듬는다: 빈 줄·중복 제거, 개인정보 가리기, 길이·개수 상한. 서버는 저장하지 않는다."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in chat or []:
        if not isinstance(raw, str):
            continue
        text = mask_text(" ".join(raw.split()))[:MAX_CHAT_CHARS].strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_CHAT_LINES:
            break
    return out


def collect(
    db: Session, user_id: str, group_id: str, today: date, chat: list[str] | None
) -> Sources:
    return Sources(
        requests=request_lines(db, group_id, user_id, today),
        billing=billing_lines(db, group_id, user_id, today),
        family=family_lines(db, user_id, group_id, today),
        chat=clean_chat(chat),
    )
