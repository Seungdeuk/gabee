from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.ai_guard import day_start
from app.shared.errors import ApiError
from app.shared.notifications import notify

from . import repository
from .schemas import (
    AdminAiFamilyRow,
    AdminAiFeatureRow,
    AdminAiLimitedRow,
    AdminAiUsageOut,
    AdminAiUserRow,
    AdminMeOut,
    AdminNoticeIn,
    AdminNoticeRow,
    AdminNoticesOut,
    AdminTicketRow,
    AdminTicketsOut,
    AdminTicketUpdate,
    FeatureRow,
    FeaturesOut,
    GroupRow,
    GroupSize,
    GroupsOut,
    MemberRow,
    MembersOut,
)

WEEK = timedelta(days=7)

# (key, 화면 이름, 표, 시각 칸). 개수만 센다.
FEATURES = (
    ("schedule", "일정", "events", "created_at"),
    ("chat", "소통", "messages", "created_at"),
    ("billing", "정산", "expenses", "created_at"),
)


DAY = timedelta(days=1)

# ai_usage_logs.feature → 화면 이름. 목록에 없는 값은 key 를 그대로 보여 준다
AI_FEATURE_NAMES = {
    "assistant_chat": "AI 비서 채팅",
    "knowledge_ask": "기록 질문",
    "schedule_chat": "일정 에이전트",
    "schedule_card": "일정 카드 만들기",
    "billing_agent": "정산 에이전트",
    "family_chat_agent": "가족 채팅 에이전트",
    "analysis": "가족 채팅 분석",
    "reply": "답장 추천",
    "topics": "대화 주제 추천",
    "doc_summary": "문서 요약(이전 기능)",
    "doc_answer": "문서 질문(이전 기능)",
}


def me_out(user: User) -> AdminMeOut:
    return AdminMeOut(id=user.id, name=user.name, login_id=user.login_id)


MEMBER_DAYS = 30


def _aware(at: datetime | None) -> datetime | None:
    """SQLite 는 시간대 없는 값을 돌려준다(UTC 로 저장했다)."""
    return at.replace(tzinfo=UTC) if at is not None and at.tzinfo is None else at


def member_daily(
    db: Session, now: datetime, *, first: datetime | None = None, days: int = MEMBER_DAYS
) -> dict[str, list[int]]:
    """회원 카드별 하루 그래프(30일 전 → 오늘, 한국 시간 자정 경계). 표마다 시각만 한 번씩 읽어 날짜별로 센다.
    first(그날 0시, UTC)·days 를 주면 그 기간을 센다(관리자 챗봇의 날짜 지정 질문). 비우면 화면과 같은 최근 30일.
    total·no_family·verified 는 그날 끝 기준 누적, joined 는 그날 가입, active 는 그날 토큰을 받은 사람 수.
    가족을 떠나거나 토큰이 지워진 기록은 남지 않아서 지난날 값은 지금 남은 기록으로 센 것이다."""
    start = first if first is not None else day_start(now) - (days - 1) * DAY
    ends = [start + (i + 1) * DAY for i in range(days)]
    t = repository.member_timestamps(db, start)
    created = [_aware(a) for a in t["created"]]
    verified = [_aware(a) for a in t["verified"] if a is not None]
    first_family = {uid: _aware(a) for uid, a in t["first_family"]}
    created_by_user = {uid: _aware(a) for uid, a in t["users"]}
    active = [(uid, _aware(a)) for uid, a in t["tokens"]]

    def before(times: list[datetime], end: datetime) -> int:
        return sum(1 for a in times if a < end)

    out: dict[str, list[int]] = {
        "total": [],
        "joined": [],
        "active": [],
        "no_family": [],
        "verified": [],
    }
    for end in ends:
        total = before(created, end)
        with_family = sum(
            1 for uid, a in first_family.items() if a < end and created_by_user.get(uid, end) < end
        )
        out["total"].append(total)
        out["joined"].append(sum(1 for a in created if end - DAY <= a < end))
        out["active"].append(len({uid for uid, a in active if end - DAY <= a < end}))
        out["no_family"].append(total - with_family)
        out["verified"].append(before(verified, end))
    return out


def members(db: Session, now: datetime | None = None) -> MembersOut:
    now = now or datetime.now(UTC)
    active_7d, no_family, email_verified = repository.member_totals(db, now - WEEK)
    daily = member_daily(db, now)
    return MembersOut(
        total=repository.count_users(db),
        joined_this_week=repository.count_users(db, since=now - WEEK),
        active_7d=active_7d,
        no_family=no_family,
        email_verified=email_verified,
        daily_joined=daily["joined"],
        daily_total=daily["total"],
        daily_active=daily["active"],
        daily_no_family=daily["no_family"],
        daily_verified=daily["verified"],
        rows=[
            MemberRow(
                id=r["id"],
                name=r["name"],
                login_id=r["login_id"],
                joined_at=r["created_at"],
                has_family=bool(r["has_family"]),
                email_verified=bool(r["email_verified"]),
                last_login_at=r["last_login_at"],
            )
            for r in repository.recent_members(db)
        ],
    )


def groups(db: Session) -> GroupsOut:
    total, rows = repository.groups_with_counts(db)
    sizes = Counter(r["members"] for r in rows)
    pending_total, oldest_pending_at, ai_enabled = repository.join_and_ai_totals(db)
    return GroupsOut(
        total=total,
        single_member=sizes.get(1, 0),
        pending_total=pending_total,
        oldest_pending_at=oldest_pending_at,
        ai_enabled=ai_enabled,
        rows=[
            GroupRow(**{**r, "ai_enabled": bool(r["ai_enabled"])})
            for r in rows[: repository.LIST_LIMIT]
        ],
        sizes=[GroupSize(members=k, groups=v) for k, v in sorted(sizes.items())],
    )


def features(db: Session, now: datetime | None = None) -> FeaturesOut:
    now = now or datetime.now(UTC)
    rows = []
    for key, name, table, col in FEATURES:
        uses, families = repository.feature_usage(db, table, col, now - WEEK, now)
        prev_uses, _ = repository.feature_usage(db, table, col, now - 2 * WEEK, now - WEEK)
        rows.append(
            FeatureRow(key=key, name=name, families=families, uses=uses, prev_uses=prev_uses)
        )
    return FeaturesOut(families_total=repository.count_groups(db), rows=rows)


def _limited(hits: list[dict]) -> list[AdminAiLimitedRow]:
    """한도에 막힌 기록(최근순)을 사람별로 묶는다. 날짜는 한국 시간 자정 경계로 센다."""
    by_user: dict[str, dict] = {}
    for h in hits:
        at = h["created_at"]
        if at.tzinfo is None:  # SQLite 는 시간대를 떼고 돌려준다
            at = at.replace(tzinfo=UTC)
        u = by_user.setdefault(
            h["user_id"],
            {"name": h["name"], "group_name": h["group_name"], "last_at": at, "days": set()},
        )
        u["days"].add(day_start(at))
    rows = [
        AdminAiLimitedRow(
            user_id=uid,
            name=u["name"],
            group_name=u["group_name"],
            days=len(u["days"]),
            last_at=u["last_at"],
        )
        for uid, u in by_user.items()
    ]
    rows.sort(key=lambda r: r.last_at, reverse=True)
    return rows[: repository.LIST_LIMIT]


def ai_daily(db: Session, first: datetime, days: int) -> list[int]:
    """first(그날 0시, UTC)부터 days 일 동안의 날짜별 AI 요청 수(오래된 날 → 최근)."""
    return [
        repository.count_ai_requests(db, first + i * DAY, first + (i + 1) * DAY)
        for i in range(days)
    ]


def ai_usage(db: Session, now: datetime | None = None) -> AdminAiUsageOut:
    now = now or datetime.now(UTC)
    today = day_start(now)
    month_start = today - 29 * DAY
    return AdminAiUsageOut(
        today=repository.count_ai_requests(db, today),
        week=repository.count_ai_requests(db, today - 6 * DAY),
        month=repository.count_ai_requests(db, month_start),
        daily=ai_daily(db, today - 13 * DAY, 14),
        rows=[
            AdminAiFeatureRow(
                key=key,
                name=AI_FEATURE_NAMES.get(key, key),
                calls=direct + via,
                direct=direct,
                via_assistant=via,
            )
            for key, direct, via in repository.ai_requests_by_feature(db, month_start)
        ],
        families=[AdminAiFamilyRow(**r) for r in repository.ai_requests_by_group(db, month_start)],
        users=[AdminAiUserRow(**r) for r in repository.ai_requests_by_user(db, month_start)],
        limited=_limited(repository.ai_limit_hits(db, month_start)),
    )


def support(db: Session) -> AdminTicketsOut:
    counts = repository.support_counts(db)
    return AdminTicketsOut(
        new=counts.get("new", 0),
        working=counts.get("working", 0),
        done=counts.get("done", 0),
        reports=counts["report"],
        rows=[AdminTicketRow(**r) for r in repository.support_tickets(db)],
    )


def update_support(
    db: Session, ticket_id: str, body: AdminTicketUpdate, now: datetime | None = None
) -> None:
    """상태와 답변 중 준 것만 바꾼다(2026-11-05 결정).
    - 답변을 저장하면 상태는 자동으로 done(답변 완료)이 되고 답변 시각을 적는다. 답변은 다시 저장해 고칠 수 있다(마지막 값만 남긴다).
    - 답변 없이는 done 으로 바꿀 수 없다(422 answer_required)."""
    values: dict = {}
    if body.status is not None:
        values["status"] = body.status
    if body.answer is not None:
        values["answer"] = body.answer.strip()
        values["answered_at"] = now or datetime.now(UTC)
        values["status"] = "done"
    if not values:
        raise ApiError(422, "nothing_to_update", "바꿀 상태나 답변을 보내 주세요")
    ticket = repository.get_support_ticket(db, ticket_id)
    if ticket is None:
        raise ApiError(404, "not_found", "찾을 수 없어요")
    if values.get("status") == "done" and not (values.get("answer") or ticket["answer"]):
        raise ApiError(422, "answer_required", "답변을 저장해야 답변 완료로 바꿀 수 있어요")
    if not repository.update_support_ticket(db, ticket_id, values):
        raise ApiError(404, "not_found", "찾을 수 없어요")
    answer = values.get("answer")
    if answer and answer != (ticket["answer"] or ""):  # 새 답변이나 고친 답변만 알린다
        # 문의 제목·내용·답변은 알림에 넣지 않는다(고정 문구). 가족과 무관하게 보낸 사람에게만 간다.
        notify(
            db,
            group_id=None,
            kind="support",
            event="ticket_answered",
            recipients=[ticket["user_id"]],
            title="문의에 답변이 달렸어요",
            target_type="support_ticket",
            target_id=ticket_id,
        )
    db.commit()


def notices(db: Session) -> AdminNoticesOut:
    return AdminNoticesOut(rows=[AdminNoticeRow(**r) for r in repository.notices(db)])


def _notice_values(body: AdminNoticeIn, now: datetime) -> dict:
    return {
        "category": body.category,
        "title": body.title.strip(),
        "body": body.body.strip(),
        "updated_at": now,
    }


def create_notice(
    db: Session, user: User, body: AdminNoticeIn, now: datetime | None = None
) -> AdminNoticeRow:
    now = now or datetime.now(UTC)
    values = {**_notice_values(body, now), "created_by": user.id, "created_at": now}
    row = repository.add_notice(db, values)
    db.commit()
    return AdminNoticeRow(**row)


def update_notice(
    db: Session, notice_id: str, body: AdminNoticeIn, now: datetime | None = None
) -> None:
    if not repository.update_notice(db, notice_id, _notice_values(body, now or datetime.now(UTC))):
        raise ApiError(404, "not_found", "찾을 수 없어요")
    db.commit()


def delete_notice(db: Session, notice_id: str) -> None:
    if not repository.delete_notice(db, notice_id):
        raise ApiError(404, "not_found", "찾을 수 없어요")
    db.commit()
