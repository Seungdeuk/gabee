"""일정 에이전트 진입점. 메인 오케스트레이터(개인·가족 채팅)가 부르고, 그 전에는 일정 라우터가 부른다.

한 번의 LLM 호출로 요청 종류와 답을 함께 받고(chat.py), 코드가 종류별로 처리한다. 지금은 질의·등록·수정·삭제·체크·추천을 처리하고
추천은 `suggest.supply` 로 연결한다. 수정·삭제는 확인 카드를 거친 뒤 `confirm` 에서 실행한다. 일정 요청이 아니면 `not_schedule` 로 돌려줘 메인이 직접 답하게 한다.
"""

from contextvars import ContextVar
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.shared.auth import ensure_group_member

from ..constants import SUGGESTION_DISMISSED
from . import chat, checks, habits, modify, reader, register, request_flow, room_notice, suggest
from . import choice as choice_mod
from . import members as members_mod
from . import period as period_mod
from .schemas import AgentRequest, AgentResponse, Card, ConfirmRequest, SuggestionOut

FAMILY_NOTICE = (
    "가족 채팅방에서 부른 요청이라 [일정 목록]에는 가족과 공유된(공동) 일정만 있다. 목록에 없는 일정은 공동이 아니라서 "
    "보이지 않는 것일 수 있으니 '일정이 없다'고 단정하지 말고, 공동 일정에서는 찾지 못했다고 답한다."
)
NOT_READY = "이 요청은 아직 처리할 수 없어요"
RECOMMEND_TEXT = "이런 일정은 어때요?"
RECOMMEND_EXHAUSTED = "오늘 추천은 여기까지, 내일도 챙겨 드릴게요💛"
RECOMMEND_NONE = "지금은 추천드릴 일정이 없어요"
RECOMMEND_SPENT_EMPTY = "일정을 찾지 못했어요. 내일 다시 찾아볼게요😢"


def suggestion_out(s) -> SuggestionOut:
    return SuggestionOut(
        id=s.id,
        title=s.title,
        kind=s.kind,
        start_date=f"{s.start_date:%Y-%m-%d}",
        place=s.place,
        later=s.status == SUGGESTION_DISMISSED,
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
    habit_view=None,
    period_note="",
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
        " ".join(
            x for x in (FAMILY_NOTICE if request.channel == "family" else "", period_note) if x
        ),
        habit_view.lines if habit_view else None,
        set(habit_view.rows) if habit_view else None,
    )


def _wider_scope(period: period_mod.Period | None, keyword: str) -> str | None:
    parts = []
    if period:
        parts.append(f"기간 {period.widened().label()}")
    if keyword:
        parts.append(f'제목에 "{keyword}" 포함')
    return "모델이 다시 요청한 " + ", ".join(parts) if parts else None


_also_delete: ContextVar[AgentResponse | None] = ContextVar("also_delete", default=None)


def _by_title(events, probe: str) -> list:
    """제목이 말(probe)에 들어 있거나 말이 제목에 들어 있는 일정. 지금 이후 일정을 먼저, 날짜순."""
    probe = probe.strip()
    if len(probe) < 2:
        return []
    found = [
        e
        for e in events
        if e.title.strip() and (e.title.strip() in probe or probe in e.title.strip())
    ]
    today = register.today()
    found.sort(
        key=lambda e: (reader.to_local(e.starts_at).date() < today, reader.to_local(e.starts_at))
    )
    return found


def _merge_also_delete(response: AgentResponse, extra: AgentResponse) -> AgentResponse:
    """한 문장에 섞인 삭제는 주된 요청과 따로 처리한다: 주된 요청은 정책대로 하고, 삭제는 확인 카드로 묻는다(정책 #34)."""
    if response.pending_action is not None or response.intent in ("delete", "not_schedule"):
        return response
    if not (extra.pending_action or extra.choice):
        return response
    return response.model_copy(
        update={
            "text": f"{response.text}\n{extra.text}".strip(),
            "cards": [*response.cards, *extra.cards],
            "pending_action": extra.pending_action,
            "choice": extra.choice or response.choice,
        }
    )


def handle(
    db: Session,
    user_id: str,
    group_id: str,
    request: AgentRequest,
    share_all: bool = False,
    guarded: bool = True,
) -> AgentResponse:
    """직전에 수정·삭제 대상을 되물었다면(서버 기억이나 앱이 돌려준 값) 사용자의 답을 먼저 읽고, 답으로 읽을 수 없으면 새 요청으로 처리한다."""
    ensure_group_member(db, user_id, group_id)  # 라우터 밖에서 service 를 부르므로 직접 확인한다
    asked = choice_mod.take(group_id, user_id) or request.choice
    if asked is not None:
        if asked.kind == "register":  # 이미 있는 일정을 또 등록할지 되물은 답
            answer = register.resolve_again(
                db, user_id, group_id, asked, request.text, members_mod.load(db, group_id)
            )
        elif asked.kind.startswith("request_"):  # 부탁(같은 제목 여럿) 되묻기의 답
            answer = request_flow.resolve_choice(
                db,
                user_id,
                group_id,
                asked,
                request.text,
                register.today(),
                members_mod.load(db, group_id),
            )
        else:
            answer = modify.resolve_choice(
                db, user_id, group_id, asked, request.text, register.today()
            )
        if answer is not None:
            return answer
    _also_delete.set(None)
    response = _handle(db, user_id, group_id, request, share_all, guarded)
    extra = _also_delete.get()
    if extra is not None:
        response = _merge_also_delete(response, extra)
    choice_mod.keep(group_id, user_id, response)
    return response


def _handle(
    db: Session,
    user_id: str,
    group_id: str,
    request: AgentRequest,
    share_all: bool = False,
    guarded: bool = True,
) -> AgentResponse:
    now = datetime.now(UTC)
    local_now = now.astimezone(reader.local_tz())
    data = reader.read(db, group_id, request.channel, now, user_id)  # 내 일정만, 과거·미래 1년
    period = period_mod.extract_for_prompt(
        request.text, local_now.date()
    )  # 목록을 거를 기간(없으면 None)
    shown, omitted = reader.select_for_prompt(data.events, now, period)
    scope = f"문장에서 읽은 기간 {period.widened().label()}" if period else None
    members = members_mod.load(db, group_id)
    # 가족방(channel=family)의 답은 방에 저장되므로 부탁의 받는 분·수락 현황은 모델에게 주지 않는다
    request_view = request_flow.load(
        db, group_id, user_id, local_now.date(), detail=request.channel != "family"
    )
    habit_view = habits.load(db, user_id, group_id, request.channel)
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
        habit_view,
        period.note if period else "",
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
            habit_view,
        )
    if result.intent == "not_schedule":
        return AgentResponse(intent=result.intent)
    if result.also_delete_title and result.intent != "delete":
        # 목록(기간으로 거른 것)에 없어도 전체 일정에서 제목으로 찾는다
        matches = _by_title(data.events, result.also_delete_title)
        if matches:
            _also_delete.set(
                modify.respond_delete(
                    user_id,
                    matches[0].id,
                    {e.id: e for e in matches},
                    register.today(),
                    request.text,
                )
            )
    found_by_title: dict = {}
    known_ids = {e.id for e in data.events}
    if result.intent in ("edit", "delete") and not (
        (result.target_id in known_ids) or result.target_unnamed or result.all_targets
    ):
        # 모델이 대상을 못 골랐거나 목록에 없는 id 를 골랐어도 말에 일정 제목이 들어 있으면 전체 일정에서 찾는다(목록이 기간으로 걸러져 빠진 경우)
        matches = _by_title(data.events, request.text)
        if matches:
            found_by_title = {e.id: e for e in matches}
            result = replace(result, target_id=matches[0].id)
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
            request.text,
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
            register.today(),
            request.text,
        )
    if result.intent == "habit":
        return habits.respond(
            habit_view,
            user_id,
            result.habit["action"],
            result.habit["item_ids"],
            result.habit["amount"],
            request.channel,
        )
    by_id = {**{e.id: e for e in shown}, **found_by_title}
    if result.intent == "edit":
        return modify.respond_edit(
            user_id,
            result.target_id,
            result.changes,
            by_id,
            register.today(),
            members,
            request.channel,
            db,
            group_id,
            request.text,
            set(result.event_ids),
            result.reply,
            result.target_unnamed,
        )
    if result.intent == "delete":
        return modify.respond_delete(
            user_id,
            result.target_id,
            by_id,
            register.today(),
            request.text,
            set(result.event_ids),
            # '다·전부·모두'라는 말이 있을 때만 여러 건 삭제로 본다. 아니면 같은 이름이 여럿일 때 어느 쪽인지 되묻는다
            result.event_ids
            if result.all_targets and choice_mod.ALL_WORDS.search(request.text)
            else (),
            result.target_unnamed,
        )
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
        # 개인 채팅에서만 공동 일정 제목 뒤에 (공), 함께하기(부탁) 제목 뒤에 (함)을 붙인다(DB 값 기준, 가족 채팅은 공동 일정만 다뤄서 생략)
        marked = result.reply
        if request.channel == "personal":
            tagged = [
                (e.title, chat.SHARED_MARK if getattr(e, "shared", False) else "") for e in picked
            ]
            tagged += [(r["title"], chat.TOGETHER_MARK) for r in asked]
            marked = chat.mark_titles(result.reply, tagged)
        text = marked or "해당하는 일정을 찾지 못했어요"
        return AgentResponse(intent=result.intent, text=text, cards=cards)
    if result.intent == "recommend":
        # 채팅 호출(분류)은 이미 했으므로 여기서는 카드 한도(schedule_card)만 추가로 쓴다
        slot = suggest.supply_slot(db, user_id, group_id, raise_errors=True)
        items = slot.items
        if items:
            text = result.reply or RECOMMEND_TEXT
        elif slot.state == suggest.STATE_EXHAUSTED:
            text = RECOMMEND_EXHAUSTED
        elif slot.state == suggest.STATE_SPENT_EMPTY:
            text = RECOMMEND_SPENT_EMPTY
        else:
            text = RECOMMEND_NONE
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
    """확인 카드의 버튼. AI 를 부르지 않는다. 앱이 돌려준 내용은 믿지 않고 처음부터 다시 검증한다.
    가족방 @가비 카드(`post_to_room`)에서 공유 등록을 마쳤으면 결과를 방에 알린다."""
    response = _confirm(db, user_id, group_id, body)
    room_notice.post_if_needed(db, group_id, body, response)
    return response


def _confirm(db: Session, user_id: str, group_id: str, body: ConfirmRequest) -> AgentResponse:
    ensure_group_member(db, user_id, group_id)
    action = body.action
    if action.type == "edit":
        return modify.confirm_edit(db, user_id, group_id, action)
    if action.type == "delete":
        return modify.confirm_delete(db, user_id, group_id, action)
    if action.type == "habit_check":
        return habits.confirm(db, user_id, action)
    if action.type == "choice":  # 선택 카드: 체크한 것을 확인 카드 없이 바로 처리한다(정책 #39)
        if action.choice_kind in ("request_edit", "request_cancel"):
            return request_flow.apply_choice(
                db, user_id, group_id, action, register.today(), members_mod.load(db, group_id)
            )
        return modify.apply_choice(db, user_id, group_id, action, register.today())
    members = members_mod.load(db, group_id)
    if action.type.startswith("request_"):
        return request_flow.confirm(db, user_id, group_id, action, members)
    return register.confirm(db, user_id, group_id, action, body.share, members)
