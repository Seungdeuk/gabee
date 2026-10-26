"""일정 에이전트 진입점. 메인 오케스트레이터(개인·가족 채팅)가 부르고, 그 전에는 일정 라우터가 부른다.

한 번의 LLM 호출로 요청 종류와 답을 함께 받고(chat.py), 코드가 종류별로 처리한다. 지금은 질의·등록·수정·삭제를 처리하고
나머지(추천·체크)는 다음 단계에서 채운다. 수정·삭제는 확인 카드를 거친 뒤 `confirm` 에서 실행한다. 일정 요청이 아니면 `not_schedule` 로 돌려줘 메인이 직접 답하게 한다.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.shared.auth import ensure_group_member

from . import chat, modify, reader, register
from . import members as members_mod
from . import period as period_mod
from .schemas import AgentRequest, AgentResponse, Card, ConfirmRequest

NOT_READY = "이 요청은 아직 처리할 수 없어요"


def _ask(
    db, user_id, group_id, request, local_now, shown, omitted, scope, final, members
) -> chat.ChatResult:
    lines = [
        chat.event_line(e.id, reader.to_local(e.starts_at), e.title, reader.time_text(e))
        for e in shown
    ]
    return chat.converse(
        db,
        user_id,
        group_id,
        request.text,
        local_now,
        lines,
        omitted,
        scope,
        {e.id for e in shown},
        final,
        members,
        request.draft,
    )


def _wider_scope(period: period_mod.Period | None, keyword: str) -> str | None:
    parts = []
    if period:
        parts.append(f"기간 {period.widened().label()}")
    if keyword:
        parts.append(f'제목에 "{keyword}" 포함')
    return "모델이 다시 요청한 " + ", ".join(parts) if parts else None


def handle(db: Session, user_id: str, group_id: str, request: AgentRequest) -> AgentResponse:
    ensure_group_member(db, user_id, group_id)  # 라우터 밖에서 service 를 부르므로 직접 확인한다
    now = datetime.now(UTC)
    local_now = now.astimezone(reader.local_tz())
    data = reader.read(db, group_id, request.channel, now, user_id)  # 내 일정만, 과거·미래 1년
    period = period_mod.extract(request.text, local_now.date())  # 문장의 기간(없으면 None)
    shown, omitted = reader.select_for_prompt(data.events, now, period)
    scope = f"문장에서 읽은 기간 {period.widened().label()}" if period else None
    members = members_mod.load(db, group_id)
    result = _ask(db, user_id, group_id, request, local_now, shown, omitted, scope, False, members)
    if result.need_wider:
        # 목록이 부족하다고 모델이 표시하면, 모델이 돌려준 기간·키워드로 이미 읽어 둔 일정 안에서 다시 걸러 한 번 더 묻는다
        model_period = period_mod.from_model(
            result.period_start, result.period_end, local_now.date()
        )
        shown, omitted = reader.select_by_model(data.events, now, model_period, result.keyword)
        result = _ask(
            db,
            user_id,
            group_id,
            request,
            local_now,
            shown,
            omitted,
            _wider_scope(model_period, result.keyword),
            True,
            members,
        )
    if result.intent == "not_schedule":
        return AgentResponse(intent=result.intent)
    if result.intent == "register":
        return register.respond(
            db, user_id, group_id, request.draft, result.register, result.reply, members
        )
    by_id = {e.id: e for e in shown}
    if result.intent == "edit":
        return modify.respond_edit(
            user_id, result.target_id, result.changes, by_id, register.today()
        )
    if result.intent == "delete":
        return modify.respond_delete(user_id, result.target_id, by_id)
    if result.intent == "query":
        picked = [by_id[i] for i in result.event_ids if i in by_id]
        cards = (
            [Card(type="event_list", data={"events": [reader.brief(e) for e in picked]})]
            if picked
            else []
        )
        text = result.reply or "해당하는 일정을 찾지 못했어요"
        return AgentResponse(intent=result.intent, text=text, cards=cards)
    return AgentResponse(intent=result.intent, text=NOT_READY)


def confirm(db: Session, user_id: str, group_id: str, body: ConfirmRequest) -> AgentResponse:
    """확인 카드의 버튼. AI 를 부르지 않는다. 앱이 돌려준 내용은 믿지 않고 처음부터 다시 검증한다."""
    ensure_group_member(db, user_id, group_id)
    action = body.action
    if action.type == "edit":
        return modify.confirm_edit(db, user_id, group_id, action)
    if action.type == "delete":
        return modify.confirm_delete(db, user_id, group_id, action)
    members = members_mod.load(db, group_id)
    return register.confirm(db, user_id, group_id, action, body.share, members)
