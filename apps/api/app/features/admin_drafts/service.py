"""관리자 AI 초안(프로액티브): 관리자가 묻기 전에 알림·문의를 먼저 보고 공지 초안·답변 초안을 만들어 대기함에 둔다.

- 언제: 알림 점검(/internal/alerts/run)이 끝난 뒤 후속 작업으로, 또는 관리자의 "지금 분석" 버튼으로.
- 공지 초안: 최근 6시간 '긴급'·'주의' 알림(숫자만 든 문구)과 문의 건수를 Claude 에 보내 공지가 필요한지 판단하게 한다.
  같은 알림 묶음으로는 한 번만, 공지 초안은 6시간에 하나까지 만든다.
- 답변 초안: 답변 없는 새 문의를 한 번에 최대 5개, 제목·내용을 가린 뒤(mask_text) 보낸다. 보낸 사람·가족 정보는 보내지 않는다.
- 자동 공지(AUTO_NOTICE_ENABLED): 서버 오류율 '긴급' 알림이 새로 생기면 정해 둔 문구로 공지를 바로 올린다. AI 를 쓰지 않는다. 6시간에 한 번.
- 지어낸 내용 줄이기: 초안에 주제·알림에 없는 숫자가 있거나(공지), 가려진 이름·외국어 낱말·약속하는 말이 있으면(답변)
  무엇이 문제인지 알려 주고 한 번만 다시 쓰게 한다. 요일은 주제에 없으면 지운다(날짜 계산을 틀리기 쉽다).
- 초안은 앱에 올라가지 않는다. 관리자가 공지·답변 칸으로 옮겨 고친 뒤 저장해야 회원에게 보인다.
"""

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared.config import settings
from app.shared.errors import ApiError, not_found
from app.shared.llm import client as llm

from . import repository
from .models import AdminDraft
from .schemas import DraftListOut, DraftOut, DraftRunOut

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
KST = ZoneInfo("Asia/Seoul")
WINDOW = timedelta(hours=6)  # 공지 판단에 쓰는 알림 기간, 공지 초안·자동 공지 사이 최소 간격
AUTO_WINDOW = timedelta(
    hours=1
)  # 자동 공지는 최근 1시간 안에 생긴 긴급 알림만 본다(오래된 장애로 뒤늦게 올리지 않게)
AUTO_RULES = ("server_error_rate",)  # 자동 공지를 올리는 규칙(ops_admin 서버 오류율)
REPLY_BATCH = 5  # 한 번에 만드는 답변 초안 수(비용 상한)
MAX_TOKENS = 1200
MAX_BODY = 1500
CALL_ERRORS = (llm.LLMUnavailable, httpx.HTTPError, ValueError, KeyError)

AUTO_TITLE = "서비스 이용이 원활하지 않아요"
AUTO_BODY = (
    "{since}부터 일부 기능이 원활하지 않은 문제가 있어 확인하고 있어요. "
    "이용에 불편을 드려 죄송해요. 문제가 해결되면 다시 알려 드릴게요."
)

NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "needed": {"type": "boolean"},
        "category": {"type": "string", "enum": ["update", "info", "maintenance"]},
        "title": {"type": "string"},
        "body": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["needed", "category", "title", "body", "reason"],
    "additionalProperties": False,
}
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "enum": ["버그", "사용법", "계정", "가족 그룹", "결제", "신고", "제안", "기타"],
        },
        "answer": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["topic", "answer", "reason"],
    "additionalProperties": False,
}


# mask_text 가 놓치는 계좌번호: "국민 123456-78-901234" 처럼 '계좌' 라벨 없이 은행 이름만 붙거나 숫자만 온 경우
_BANKS = "국민|신한|우리|하나|농협|기업|카카오|토스|케이|수협|부산|대구|경남|광주|전북|제주|산업|씨티|우체국|새마을"
_BANK_ACCOUNT = re.compile(rf"((?:{_BANKS})(?:은행|뱅크|금고)?\s*)(\d[\d -]{{7,}}\d)")
_LONG_NUMBER = re.compile(
    r"(?<![\d*-])\d{2,6}(?:-\d{2,8}){1,3}(?![\d*-])|(?<![\d*-])\d{10,}(?![\d*-])"
)
_CONTACT = re.compile(r"\d{2,4}[-.\s]?\d{3,4}[-.\s]?\d{4}|[\w.+-]+@[\w-]+\.[\w.]+")
_WEEKDAY = re.compile(r"\s*\((?:월|화|수|목|금|토|일)(?:요일)?\)")
_MASKED_NAME = re.compile(r"[가-힣]{1,2}\*+\s*(?=회원님|고객님|님)")
_LATIN = re.compile(r"[A-Za-z]{2,}")
_PROMISE = re.compile(r"보상해|환불해 드|환불 처리해|까지 해결|까지 처리|반드시|약속")
LATIN_OK = {"ai", "gabee", "ios", "android", "os", "pc", "pdf", "sms", "id", "wifi", "app", "store"}


def _mask(text: str) -> str:
    """Claude 로 보내기 전에 가린다: 공통 가림(mask_text) + 라벨 없는 계좌번호·긴 번호."""
    text = _BANK_ACCOUNT.sub(lambda m: m.group(1) + re.sub(r"\d", "*", m.group(2)), mask_text(text))
    return _LONG_NUMBER.sub(
        lambda m: (
            re.sub(r"\d", "*", m.group(0))
            if sum(c.isdigit() for c in m.group(0)) >= 10
            else m.group(0)
        ),
        text,
    )


def _unmask_contacts(text: str, topic: str) -> str:
    """관리자가 공지 주제에 직접 적은 연락처는 초안에서 원래 값으로 되돌린다(Claude 에는 가린 값만 갔다)."""
    for raw in _CONTACT.findall(topic):
        masked = _mask(raw)
        if masked != raw:
            text = text.replace(masked, raw)
    return text


def _new_numbers(text: str, source: str) -> list[str]:
    """초안에 있는데 보낸 내용(주제·알림)에는 없는 숫자. 9시 와 09:00 은 같은 수로 본다."""
    have = {int(n) for n in re.findall(r"\d+", source)}
    return sorted({n for n in re.findall(r"\d+", text) if int(n) not in have})


def _prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def _reply_system() -> str:
    guide = PROMPTS / "app_guide.md"
    extra = f"\n\n앱 안내 자료:\n{guide.read_text(encoding='utf-8')}" if guide.exists() else ""
    return _prompt("reply.md") + extra


def _ask_notice(prompt: str, topic: str = "") -> dict:
    """공지 초안을 받는다. 보낸 내용에 없는 숫자가 있으면 한 번만 다시 쓰게 하고, 요일·가려진 연락처를 손본다."""
    system = _prompt("notice.md")
    data = llm.complete_json(prompt, NOTICE_SCHEMA, system=system, max_tokens=MAX_TOKENS).data
    extra = _new_numbers(f"{data.get('title', '')}\n{data.get('body', '')}", prompt)
    if extra and data.get("needed"):
        again = (
            f"{prompt}\n\n앞서 쓴 초안에 위 내용에 없는 숫자({', '.join(extra)})가 들어갔습니다. "
            "그 숫자가 든 표현을 빼고 위 내용에 있는 사실만으로 다시 쓰세요."
        )
        try:
            second = llm.complete_json(
                again, NOTICE_SCHEMA, system=system, max_tokens=MAX_TOKENS
            ).data
        except CALL_ERRORS as e:
            log.warning("admin draft notice retry failed error=%s", type(e).__name__)
        else:
            second_text = f"{second.get('title', '')}\n{second.get('body', '')}"
            if len(_new_numbers(second_text, prompt)) < len(extra):
                data = second
    for key in ("title", "body"):
        value = str(data.get(key, ""))
        if not _WEEKDAY.search(topic):
            value = _WEEKDAY.sub("", value)
        data[key] = _unmask_contacts(value, topic)
    return data


def _kst(at: datetime) -> str:
    if at.tzinfo is None:  # SQLite 는 시간대 없이 돌려준다. 저장 값은 항상 UTC 다
        at = at.replace(tzinfo=UTC)
    return at.astimezone(KST).strftime("%m월 %d일 %H시 %M분")


def _recent(last: datetime | None, now: datetime) -> bool:
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return now - last < WINDOW


def _clip(text: str, n: int) -> str:
    return text.strip()[:n]


def _auto_notice(db: Session, now: datetime) -> int:
    """서버 오류율 '긴급' 알림이 최근 1시간 안에 새로 생겼으면 정해 둔 문구로 공지를 올린다."""
    urgent = [
        a
        for a in repository.recent_alerts(db, now - AUTO_WINDOW)
        if a["severity"] == "긴급" and a["rule"] in AUTO_RULES
    ]
    if not urgent or _recent(repository.last_notice_draft_at(db, auto=True), now):
        return 0
    first = urgent[0]
    body = AUTO_BODY.format(since=_kst(first["created_at"]))
    draft = AdminDraft(
        kind="notice",
        source_key=f"auto:{first['key']}"[:120],
        category="maintenance",
        title=AUTO_TITLE,
        body=body,
        reason=f"서버 오류율 긴급 알림으로 자동 공지를 올렸어요: {first['message']}"[:300],
        status="used",
        auto=True,
        created_at=now,
        updated_at=now,
    )
    if not repository.add_draft(db, draft):
        return 0
    draft.notice_id = repository.add_notice(db, "maintenance", AUTO_TITLE, body, now)
    return 1


def _notice_draft(db: Session, now: datetime) -> int:
    alerts = [
        a for a in repository.recent_alerts(db, now - WINDOW) if a["severity"] in ("긴급", "주의")
    ]
    if not alerts:
        return 0
    source = (
        "notice:"
        + hashlib.sha1("|".join(sorted(a["key"] for a in alerts)).encode()).hexdigest()[:20]
    )
    if repository.has_draft(db, "notice", source) or _recent(
        repository.last_notice_draft_at(db, auto=False), now
    ):
        return 0
    counts = repository.ticket_counts(db, now - timedelta(hours=24))
    lines = [
        f"- [{a['severity']}] {a['message']} (확인할 곳: {a['menu']}, {_kst(a['created_at'])})"
        for a in alerts
    ]
    prompt = (
        f"지금 시각: {_kst(now)} (한국 시간)\n"
        f"최근 6시간 관리자 알림:\n" + "\n".join(lines) + "\n"
        f"최근 24시간 문의 {counts.get('inquiry', 0)}건, 신고 {counts.get('report', 0)}건"
    )
    try:
        data = _ask_notice(prompt)
    except CALL_ERRORS as e:
        log.warning("admin draft notice failed error=%s", type(e).__name__)
        return 0
    needed = bool(data.get("needed")) and bool(str(data.get("body", "")).strip())
    draft = AdminDraft(
        kind="notice",
        source_key=source,
        category=data.get("category")
        if data.get("category") in ("update", "info", "maintenance")
        else "info",
        title=_clip(str(data.get("title", "")), 100) or None,
        body=_clip(str(data.get("body", "")), MAX_BODY),
        reason=_clip(str(data.get("reason", "")), 300) or "근거 없음",
        # 공지가 필요 없다고 봤으면 대기함에 띄우지 않고 기록만 남긴다(같은 알림으로 다시 묻지 않게)
        status="pending" if needed else "dismissed",
        created_at=now,
        updated_at=now,
    )
    return 1 if repository.add_draft(db, draft) and needed else 0


def make_notice(db: Session, topic: str, now: datetime | None = None) -> DraftOut:
    """관리자가 [AI 공지 초안]을 누를 때: 적은 주제(없으면 최근 알림)로 공지 초안을 지금 만든다.
    만든 초안은 대기함에 두고 돌려준다(화면이 바로 공지 쓰기 칸에 채운다). 주제는 가린 뒤 보낸다."""
    now = now or datetime.now(UTC)
    if not settings.admin_drafts_enabled:
        raise ApiError(409, "drafts_disabled", "AI 초안이 꺼져 있어요")
    topic = topic.strip()
    alerts = [
        a for a in repository.recent_alerts(db, now - WINDOW) if a["severity"] in ("긴급", "주의")
    ]
    if not topic and not alerts:
        raise ApiError(
            422, "topic_required", "최근 서버 알림이 없어요. 어떤 공지를 쓸지 적어 주세요"
        )
    lines = [
        f"- [{a['severity']}] {a['message']} (확인할 곳: {a['menu']}, {_kst(a['created_at'])})"
        for a in alerts
    ]
    # 주제로 쓰는 공지에는 지금 '시각'을 주지 않는다(문제 시작 시각처럼 옮겨 쓰는 일이 있었다). 날짜만 준다
    today = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(KST).strftime("%m월 %d일")
    prompt = f"오늘 날짜: {today} (한국 시간)\n"
    if topic:
        prompt += f"관리자가 쓰려는 공지: {_mask(topic)}\n"
    prompt += "최근 6시간 관리자 알림:\n" + ("\n".join(lines) if lines else "- 없음")
    try:
        data = _ask_notice(prompt, topic)
    except CALL_ERRORS as e:
        log.warning("admin draft notice failed error=%s", type(e).__name__)
        raise ApiError(
            503, "llm_unavailable", "AI 초안을 만들지 못했어요. 잠시 뒤 다시 해 주세요"
        ) from None
    body = _clip(str(data.get("body", "")), MAX_BODY)
    if not body:
        raise ApiError(503, "llm_unavailable", "AI 초안을 만들지 못했어요. 잠시 뒤 다시 해 주세요")
    category = data.get("category")
    draft = AdminDraft(
        kind="notice",
        source_key=f"manual:{uuid.uuid4().hex[:16]}",
        category=category if category in ("update", "info", "maintenance") else "info",
        title=_clip(str(data.get("title", "")), 100) or None,
        body=body,
        reason=_clip(str(data.get("reason", "")), 300) or "관리자 요청",
        created_at=now,
        updated_at=now,
    )
    db.add(draft)
    db.commit()
    return _out(draft)


def _ask_reply(t: dict) -> dict:
    """문의 한 건을 가린 뒤 Claude 에 보내 {topic, answer, reason} 을 받는다. 실패는 CALL_ERRORS 로 올린다."""
    kind = "신고" if t["kind"] == "report" else "문의"
    prompt = f"종류: {kind}\n제목: {_mask(t['title'])}\n내용:\n{_mask(t['body'])}"
    system = _reply_system()
    data = llm.complete_json(prompt, REPLY_SCHEMA, system=system, max_tokens=MAX_TOKENS).data
    issues = _reply_issues(str(data.get("answer", "")), prompt)
    if issues:
        again = (
            f"{prompt}\n\n앞서 쓴 답변에 고칠 점이 있습니다: {'; '.join(issues)}. "
            "이 점을 고쳐 다시 쓰세요."
        )
        try:
            second = llm.complete_json(
                again, REPLY_SCHEMA, system=system, max_tokens=MAX_TOKENS
            ).data
        except CALL_ERRORS as e:
            log.warning("admin draft reply retry failed error=%s", type(e).__name__)
        else:
            if len(_reply_issues(str(second.get("answer", "")), prompt)) < len(issues):
                data = second
    data["answer"] = _MASKED_NAME.sub("", str(data.get("answer", "")))
    return data


def _reply_issues(answer: str, source: str) -> list[str]:
    """답변 초안에서 기계로 잡을 수 있는 문제. 고칠 점만 돌려주고 문의 내용은 담지 않는다."""
    issues = []
    if _MASKED_NAME.search(answer) or "***" in answer:
        issues.append("가려진 이름·번호를 답변에 옮기지 말고 '회원님'이라고만 부르기")
    low = source.lower()
    odd = [w for w in _LATIN.findall(answer) if w.lower() not in LATIN_OK and w.lower() not in low]
    if odd:
        issues.append(f"외국어 낱말({', '.join(sorted(set(odd))[:5])})을 빼고 한국어로만 쓰기")
    if _PROMISE.search(answer):
        issues.append("보상·환불·처리 시각을 약속하는 말 빼기")
    return issues


def _reply_values(data: dict) -> dict:
    return {
        "title": str(data.get("topic", "기타"))[:100],
        "body": _clip(str(data.get("answer", "")), 2000),
        "reason": _clip(str(data.get("reason", "")), 300) or "근거 없음",
    }


def _reply_drafts(db: Session, now: datetime) -> int:
    made = 0
    for t in repository.tickets_needing_reply(db, REPLY_BATCH):
        try:
            values = _reply_values(_ask_reply(t))
        except CALL_ERRORS as e:
            log.warning("admin draft reply failed error=%s", type(e).__name__)
            break  # Claude 가 안 되면 나머지 문의도 실패할 것이라 이번 차례는 멈춘다
        if not values["body"]:
            continue
        draft = AdminDraft(
            kind="reply",
            source_key=f"reply:{t['id']}",
            ticket_id=t["id"],
            created_at=now,
            updated_at=now,
            **values,
        )
        if repository.add_draft(db, draft):
            made += 1
    return made


def make_reply(db: Session, ticket_id: str, now: datetime | None = None) -> DraftOut:
    """문의 하나의 답변 초안을 지금 만든다(관리자가 문의를 펼쳐 [AI 답변 초안 만들기]를 누를 때).
    상태와 상관없이 만들고, 전에 만든 초안이 있으면(버렸어도) 새 내용으로 바꿔 다시 대기로 둔다."""
    now = now or datetime.now(UTC)
    if not settings.admin_drafts_enabled:
        raise ApiError(409, "drafts_disabled", "AI 초안이 꺼져 있어요")
    t = repository.get_ticket(db, ticket_id)
    if t is None:
        raise not_found("문의")
    try:
        values = _reply_values(_ask_reply(t))
    except CALL_ERRORS as e:
        log.warning("admin draft reply failed error=%s", type(e).__name__)
        raise ApiError(
            503, "llm_unavailable", "AI 초안을 만들지 못했어요. 잠시 뒤 다시 해 주세요"
        ) from None
    if not values["body"]:
        raise ApiError(503, "llm_unavailable", "AI 초안을 만들지 못했어요. 잠시 뒤 다시 해 주세요")
    draft = repository.get_by_source(db, "reply", f"reply:{ticket_id}")
    if draft is None:
        draft = AdminDraft(
            kind="reply", source_key=f"reply:{ticket_id}", ticket_id=ticket_id, created_at=now
        )
        db.add(draft)
    for k, v in values.items():
        setattr(draft, k, v)
    draft.status = "pending"
    draft.updated_at = now
    db.commit()
    return _out(draft)


def run(db: Session, now: datetime | None = None) -> DraftRunOut:
    """한 차례 분석한다. 둘 다 꺼져 있으면 아무것도 하지 않는다."""
    now = now or datetime.now(UTC)
    if not (settings.admin_drafts_enabled or settings.auto_notice_enabled):
        return DraftRunOut(enabled=False, notices=0, replies=0, published=0)
    published = _auto_notice(db, now) if settings.auto_notice_enabled else 0
    db.commit()
    notices = replies = 0
    if settings.admin_drafts_enabled:
        notices = _notice_draft(db, now)
        db.commit()
        replies = _reply_drafts(db, now)
        db.commit()
    return DraftRunOut(enabled=True, notices=notices, replies=replies, published=published)


def followup(db: Session, now: datetime) -> None:
    """알림 점검 뒤 후속 작업(app.shared.alert_rules.register_followup)."""
    run(db, now)


def _out(d: AdminDraft) -> DraftOut:
    return DraftOut.model_validate(d, from_attributes=True)


def list_drafts(db: Session) -> DraftListOut:
    return DraftListOut(
        enabled=settings.admin_drafts_enabled,
        auto_notice_enabled=settings.auto_notice_enabled,
        pending=[_out(d) for d in repository.pending(db)],
        auto_notices=[_out(d) for d in repository.recent_auto_notices(db)],
    )


def set_status(db: Session, draft_id: str, status: str) -> bool:
    ok = repository.set_status(db, draft_id, status, datetime.now(UTC))
    db.commit()
    return ok
