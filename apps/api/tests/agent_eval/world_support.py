"""월드 시험이 함께 쓰는 도우미(가짜 모델·외부 호출 없음, 앱의 공개 API 와 도구만 읽는다)."""

import hashlib
import json

from evals.agent_eval import env
from evals.agent_eval.seeds import inspect_world as look

MONTHS = ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11")
USERS = ("지민", "수진", "민수", "남")

# 월드 해시에 세는 표는 이 목록뿐이다: 해시를 처음 고정한 시점(a4cff7fc)의 모든 표(86개).
# 이후 다른 기능이 새 표를 더해도(예: play_photo_rec) 월드가 만든 데이터는 그대로인데 해시만 달라지는 일이 없게 한다.
# 대신 목록 밖의 표에 월드가 행을 만들면 시험(	est_tables_added_after_the_pin_stay_empty)이 잡는다.
PINNED_TABLES = frozenset(
    {
        "admin_alert_log",
        "agent_proposal_uses",
        "ai_group_settings",
        "ai_inflight",
        "ai_result_cache",
        "ai_usage_logs",
        "allowance_entries",
        "allowance_plans",
        "allowance_requests",
        "allowance_uses",
        "allowances",
        "assistant_memories",
        "billing_settings",
        "chat_board_posts",
        "chat_message_links",
        "chat_photo_check_events",
        "chat_photo_checks",
        "chat_pin_hides",
        "chat_pinned_messages",
        "chat_read_states",
        "chat_room_members",
        "chat_room_mutes",
        "chat_room_reads",
        "chat_rooms",
        "document_reminders",
        "email_verifications",
        "events",
        "events_check_cheers",
        "events_check_items",
        "events_check_logs",
        "events_check_settings",
        "events_check_suggestions",
        "events_request_recipients",
        "events_requests",
        "events_suggestions",
        "events_topics",
        "expenses",
        "family_memory_jobs",
        "family_memory_settings",
        "family_todos",
        "group_members",
        "groups",
        "invite_attempts",
        "invites",
        "join_requests",
        "knowledge_chunks",
        "knowledge_item_reads",
        "knowledge_items",
        "location_consent_events",
        "member_memory_consents",
        "member_nicknames",
        "member_weekly_news",
        "memory_candidate_photos",
        "memory_candidates",
        "message_attachments",
        "message_reactions",
        "message_shares",
        "messages",
        "notices",
        "notifications",
        "ops_error_events",
        "ops_request_metrics",
        "password_resets",
        "photo_analysis_exclusions",
        "photo_embeddings",
        "photos",
        "play_answers",
        "play_bomb_players",
        "play_bomb_rounds",
        "play_bomb_turns",
        "play_draw_stock",
        "play_draws",
        "play_items",
        "play_photos",
        "play_quiz",
        "play_scores",
        "push_settings",
        "push_tokens",
        "refresh_tokens",
        "reminder_settings",
        "scheduled_push_log",
        "settlement_payments",
        "social_accounts",
        "subscription_items",
        "support_tickets",
        "users",
    }
)


def scrub(value, names):
    """다시 만들 때마다 달라지는 값(id·시각)을 뺀 비교용 값. 목록 안의 사용자 id 는 이름으로 바꾼다."""
    drop = {"id", "created_at", "updated_at", "expense_id", "user_id", "paid_by", "payer_id",
            "child_id", "manager_id", "request_id", "invite_code", "token", "decided_by"}  # fmt: skip
    if isinstance(value, dict):
        return {k: scrub(v, names) for k, v in sorted(value.items()) if k not in drop}
    if isinstance(value, list):
        return sorted((scrub(v, names) for v in value), key=repr)
    return names.get(value, value) if isinstance(value, str) else value


def billing_view(client, world) -> dict:
    """모든 사용자가 정산 API 로 읽는 값(id·시각 제외). 월드가 만든 정산 데이터의 비교용 요약."""
    out = {}
    names = {m.user_id: m.name for m in world.members.values()}
    for user in USERS:
        headers = world.headers(user)
        for month in MONTHS:
            for path in ("expenses", "summary", "settlement", "subscriptions/monthly"):
                r = look._get(client, f"/billing/{path}", headers, month=month)
                out[f"{user}|{path}|{month}"] = (
                    scrub(r.json(), names) if r.status_code == 200 else r.status_code
                )
        for path in ("subscriptions", "allowances", "settlement/manager", "settlement/tags"):
            r = look._get(client, f"/billing/{path}", headers)
            out[f"{user}|{path}"] = (
                scrub(r.json(), names) if r.status_code == 200 else r.status_code
            )
    return out


def pinned_row_counts(engine) -> dict[str, int]:
    """고정한 표(PINNED_TABLES)의 행 수만."""
    return {t: n for t, n in env.count_rows(engine).items() if t in PINNED_TABLES}


def unpinned_row_counts(engine) -> dict[str, int]:
    """고정 이후에 생긴 표(PINNED_TABLES 밖)의 행 수. 월드가 이 표에 행을 만들면 월드가 바뀐 것이다."""
    return {t: n for t, n in env.count_rows(engine).items() if t not in PINNED_TABLES}


def world_digest(client, world) -> str:
    """월드가 만든 데이터 전체의 해시: 공개 API 로 읽은 스냅샷(`inspect_world.snapshot`)·정산 값·문서 도구 결과·모든 표의 행 수.
    id·시각은 빼서 같은 선언이면 매번 같은 값이다(dev 월드 w1 의 바이트 단위 동일성 시험이 이 값을 고정해 둔다)."""
    from app.shared.db import engine

    payload = {
        "snapshot": look.snapshot(client, world),
        "billing": billing_view(client, world),
        "tools": {u: sorted(look.tool_texts(world, u)) for u in USERS},
        "rows": pinned_row_counts(engine),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=repr)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
