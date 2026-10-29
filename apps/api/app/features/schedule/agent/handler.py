"""일정 에이전트 진입점. 메인 오케스트레이터(개인·가족 채팅)가 부르고, 그 전에는 일정 라우터가 부른다.

한 번의 LLM 호출로 요청 종류와 답을 함께 받고(chat.py), 코드가 종류별로 처리한다. 지금은 질의·등록·수정·삭제·체크·추천을 처리하고
추천은 `suggest.supply` 로 연결한다. 수정·삭제는 확인 카드를 거친 뒤 `confirm` 에서 실행한다. 일정 요청이 아니면 `not_schedule` 로 돌려줘 메인이 직접 답하게 한다.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.shared.auth import ensure_group_member

from . import chat, checks, modify, reader, register, request_flow, suggest
from . import members as members_mod
from . import period as period_mod
from .schemas import AgentRequest, AgentResponse, Card, ConfirmRequest, SuggestionOut

FAMILY_NOTICE = (
    "가족 채팅방에서 부른 요청이라 [일정 목록]에는 가족과 공유된(공동) 일정만 있다. 목록에 없는 일정은 공동이 아니라서 "
    "보이지 않는 것일 수 있으니 '일정이 없다'고 단정하지 말고, 공동 일정에서는 찾지 못했다고 답한다."
)
NOT_READY = "이 요청은 아직 처리할 수 없어요"
RECOMMEND_TEXT = "이런 일정은 어때요?"
RECOMMEND_EXHAUSTED = "오늘 추천은 여기까지, 내일도 챙겨 드릴게요 💛"
RECOMMEND_NONE = "지금은 추천드릴 일정이 없어요"


def suggestion_out(s) -> SuggestionOut:
    return SuggestionOut(
        id=s.id, title=s.title, kind=s.kind, start_date=f"{s.start_date:%Y-%m-%d}", place=s.place
    )


def _ask(
    db,
    user_id,
    group_id,
    request,
    local_now,
    shown,
    omitted,
    scope,
    final,
    members,
    guarded=True,
    request_view=None,
) -> chat.ChatResult:
    lines = [
        chat.event_line(
            e.id,
            reader.to_local(e.starts_at),
            e.title,
            reader.time_text(e),
            getattr(e, "shared", False),
            modify.share_targets_for_prompt(e, user_id) if request.channel == "personal" else None,
        )
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
        guarded,
        request_view.lines if request_view else None,
        set(request_view.rows) if request_view else None,
        FAMILY_NOTICE if request.channel == "family" else "",
    )


def _wider_scope(period: period_mod.Period | None, keyword: str) -> str | None:
    parts = []
    if period:
        parts.append(f"기간 {period.widened().label()}")
    if keyword:
        parts.append(f'제목에 "{keyword}" 포함')
    return "모델이 다시 요청한 " + ", ".join(parts) if parts else None


def handle(
    db: Session,
    user_id: str,
    group_id: str,
    request: AgentRequest,
    share_all: bool = False,
    guarded: bool = True,
) -> AgentResponse:
    ensure_group_member(db, user_id, group_id)  # 라우터 밖에서 service 를 부르므로 직접 확인한다
    now = datetime.now(UTC)
    local_now = now.astimezone(reader.local_tz())
    data = reader.read(db, group_id, request.channel, now, user_id)  # 내 일정만, 과거·미래 1년
    period = period_mod.extract(request.text, local_now.date())  # 문장의 기간(없으면 None)
    shown, omitted = reader.select_for_prompt(data.events, now, period)
    scope = f"문장에서 읽은 기간 {period.widened().label()}" if period else None
    members = members_mod.load(db, group_id)
    request_view = request_flow.load(db, group_id, user_id, local_now.date())
    result = _ask(
        db,
        user_id,
        group_id,
        request,
        local_now,
        shown,
        omitted,
        scope,
        False,
        members,
        guarded,
        request_view,
    )
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
            guarded,
            request_view,
        )
    if result.intent == "not_schedule":
        return AgentResponse(intent=result.intent)
    if result.intent == "register":
        return register.respond(
            db,
            user_id,
            group_id,
            request.draft,
            result.register,
            result.reply,
            members,
            share_all,
        )
    if result.intent == "request":
        return request_flow.respond(
            db,
            user_id,
            group_id,
            request.draft,
            result.request,
            result.reply,
            members,
            request_view,
        )
    by_id = {e.id: e for e in shown}
    if result.intent == "edit":
        return modify.respond_edit(
            user_id,
            result.target_id,
            result.changes,
            by_id,
            register.today(),
            members,
            request.channel,
        )
    if result.intent == "delete":
        return modify.respond_delete(user_id, result.target_id, by_id)
    if result.intent == "check":
        return checks.respond(
            db,
            user_id,
            group_id,
            result.check_action,
            result.event_ids,
            by_id,
            data.events,
            period,
            register.today(),
        )
    if result.intent == "query":
        picked = [by_id[i] for i in result.event_ids if i in by_id]
        cards = (
            [Card(type="event_list", data={"events": [reader.brief(e) for e in picked]})]
            if picked
            else []
        )
        asked = [
            request_view.rows[i] for i in result.request["request_ids"] if i in request_view.rows
        ]
        if asked:  # 브리핑처럼 묻는 기간의 일정 옆에 내가 보낸 부탁도 함께 보여 준다
            cards.append(request_flow.list_card(asked, user_id, members))
        text = result.reply or "해당하는 일정을 찾지 못했어요"
        return AgentResponse(intent=result.intent, text=text, cards=cards)
    if result.intent == "recommend":
        # 채팅 호출(분류)은 이미 했으므로 여기서는 카드 한도(schedule_card)만 추가로 쓴다
        items, exhausted = suggest.supply(db, user_id, group_id)
        if items:
            text = result.reply or RECOMMEND_TEXT
        else:
            text = RECOMMEND_EXHAUSTED if exhausted else RECOMMEND_NONE
        cards = [
            Card(
                type="suggestion",
                data={
                    "id": s.id,
                    "title": s.title,
                    "kind": s.kind,
                    "date": f"{s.start_date:%Y-%m-%d}",
                    "place": s.place,
                },
            )
            for s in items
        ]
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
    if action.type.startswith("request_"):
        return request_flow.confirm(db, user_id, group_id, action, members)
    return register.confirm(db, user_id, group_id, action, body.share, members)
