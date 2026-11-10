"""데일리 체크 연결. 채팅에서 "오늘 약 먹었어?"를 물으면 조회하고, "약 먹었어"라고 하면 체크를 대신 눌러 준다.

- 조회: 모델에는 오늘 해당하는 습관을 한 줄씩 보내고(`load`), 답은 코드가 DB 값으로 만든다(모델이 상태를 지어내지 않게).
  내 습관은 개인 채팅에서 모두, 가족 채팅(`@가비`)에서는 "가족에게 보이기"를 켠 것만 읽는다. 다른 가족의 습관도 가족에게 보이기를 켠 것만 읽는다.
- 대신 체크: 쓰기라서 확인 카드를 거친다(`PendingAction.type == "habit_check"`). 대상은 내 습관뿐이고, 버튼을 누르면 `confirm` 이
  처음부터 다시 검증해 `check.set_entry` 로 기록한다. 가족 채팅에서 부른 요청도 카드는 질문한 사람에게만 보인다(일정 에이전트의 답은 방에 올리지 않는다).
- 횟수 습관은 `amount` 만큼 더하고(unmark 는 뺀다), 오늘 기준 절대값은 확인 단계에서 현재 값으로 계산한다.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared.errors import ApiError

from .. import check
from .. import check_repository as repo
from ..check_schemas import CheckEntryBody
from ..constants import CHECK_COUNT_MAX, CHECK_KIND_CHECK
from .schemas import AgentResponse, Card, PendingAction

MAX_HABIT_LINES = 40  # 모델에 보내는 습관 줄 수
MAX_PICKED = 20
ME = "나"
NOT_FOUND_TEXT = "어떤 습관인지 찾지 못했어요. 습관 이름을 함께 알려 주세요"
NOT_MINE_TEXT = "다른 가족의 데일리 체크는 대신 눌러 드릴 수 없어요"
NONE_TEXT = "오늘 해당하는 데일리 체크 습관이 없어요"
NONE_FAMILY_TEXT = "오늘 가족에게 보이는 데일리 체크 습관이 없어요"
CONFIRM_TITLE = "이대로 체크할까요?"
ACTIONS = ("list", "mark", "unmark")


@dataclass(frozen=True)
class HabitRow:
    id: str
    owner_id: str
    owner_name: str
    name: str
    kind: int
    goal: int | None
    unit: str
    done: bool  # 체크 습관은 완료, 횟수 습관은 목표 달성
    count: int  # 횟수 습관의 오늘 횟수(체크 습관은 0)

    @property
    def state(self) -> str:
        if self.kind == CHECK_KIND_CHECK:
            return "완료" if self.done else "아직"
        return f"{self.count}/{self.goal}{self.unit}"


@dataclass
class HabitView:
    lines: list[str] = field(default_factory=list)  # 모델에 보내는 줄: id | 주인 | 이름 | 상태
    rows: dict[str, HabitRow] = field(default_factory=dict)


def _row(item: dict, owner_id: str, owner_name: str) -> HabitRow:
    kind = item["kind"]
    count = int(item.get("count") or 0)
    goal = item.get("goal")
    done = bool(item.get("done")) if kind == CHECK_KIND_CHECK else bool(goal and count >= goal)
    return HabitRow(
        id=item["id"],
        owner_id=owner_id,
        owner_name=owner_name,
        name=item["name"],
        kind=kind,
        goal=goal,
        unit=item.get("unit") or "",
        done=done,
        count=count if kind != CHECK_KIND_CHECK else 0,
    )


def load(db: Session, user_id: str, group_id: str, channel: str) -> HabitView:
    """오늘 해당하는 습관. 내 습관(가족 채팅이면 가족에게 보이는 것만) + 다른 가족의 가족에게 보이는 습관."""
    rows: list[HabitRow] = []
    for item in check.list_items(db, user_id):
        if item["applies"] and (channel == "personal" or item["shared"]):
            rows.append(_row(item, user_id, ME))
    for member_id, name in repo.members_of(db, group_id):
        if member_id == user_id:
            continue
        for item in check.member_today(db, group_id, member_id)["items"]:
            rows.append(_row(item, member_id, name))
    rows = rows[:MAX_HABIT_LINES]
    view = HabitView(rows={r.id: r for r in rows})
    view.lines = [
        f"{r.id} | {ME if r.owner_name == ME else r.owner_id} | {mask_text(r.name)} | {r.state}"
        for r in rows
    ]
    return view


def clean_fields(data, allowed_ids: set[str]) -> dict:
    """모델 출력을 믿지 않고 검증한다: 보기 밖 action 은 비우고, 목록에 없는 id 는 버리고, amount 는 1~100."""
    data = data if isinstance(data, dict) else {}
    action = data.get("action") if data.get("action") in ACTIONS else ""
    ids = data.get("item_ids")
    seen: list[str] = []
    for value in ids if isinstance(ids, list) else []:
        if isinstance(value, str) and value in allowed_ids and value not in seen:
            seen.append(value)
    amount = data.get("amount")
    amount = amount if isinstance(amount, int) and not isinstance(amount, bool) else 1
    return {"action": action, "item_ids": seen[:MAX_PICKED], "amount": min(max(amount, 1), 100)}


def _who(row: HabitRow) -> str:
    return "" if row.owner_name == ME else f"{row.owner_name}님 "


def _list(view: HabitView, picked: list[HabitRow], channel: str) -> AgentResponse:
    rows = picked or list(view.rows.values())
    if not rows:
        return AgentResponse(
            intent="habit", text=NONE_FAMILY_TEXT if channel == "family" else NONE_TEXT
        )
    body = "\n".join(f"- {_who(r)}{r.name}: {r.state}" for r in rows)
    return AgentResponse(intent="habit", text=f"오늘 데일리 체크예요\n{body}")


def _target(row: HabitRow, op: str, amount: int) -> tuple[bool, str]:
    """(바뀌는가, 카드에 보이는 '→ 뒤' 문구)."""
    if row.kind == CHECK_KIND_CHECK:
        if op == "mark":
            return (not row.done, "완료")
        return (row.done, "아직")
    new = min(row.count + amount, CHECK_COUNT_MAX) if op == "mark" else max(row.count - amount, 0)
    return (new != row.count, f"{new}/{row.goal}{row.unit}")


def respond(
    view: HabitView, user_id: str, action: str, item_ids: list[str], amount: int, channel: str
) -> AgentResponse:
    picked = [view.rows[i] for i in item_ids if i in view.rows]
    if action == "list" or not action:
        return _list(view, picked, channel)
    if not picked:
        return AgentResponse(intent="habit", text=NOT_FOUND_TEXT)
    mine = [r for r in picked if r.owner_id == user_id]
    if not mine:
        return AgentResponse(intent="habit", text=NOT_MINE_TEXT)
    lines, ids = [], []
    for row in mine:
        changes, after = _target(row, action, amount)
        if changes:
            lines.append(f"{row.name}: {row.state} → {after}")
            ids.append(row.id)
    if not ids:
        text = "이미 모두 체크되어 있어요" if action == "mark" else "취소할 체크가 없어요"
        return AgentResponse(intent="habit", text=text)
    return AgentResponse(
        intent="habit",
        text=CONFIRM_TITLE,
        cards=[Card(type="habit_confirm", data={"lines": lines})],
        pending_action=PendingAction(
            type="habit_check", habit_ids=ids, habit_op=action, amount=amount
        ),
    )


def confirm(db: Session, user_id: str, action: PendingAction) -> AgentResponse:
    """확인 카드의 버튼. 앱이 돌려준 값은 믿지 않고 내 습관인지·오늘 상태가 어떤지 다시 읽어 기록한다."""
    today = check.today_of(check.now_utc())
    done_lines = []
    for item_id in action.habit_ids[:MAX_PICKED]:
        item = repo.item_of(db, user_id, item_id)
        if item is None:
            continue
        log = repo.log_of(db, item.id, today)
        try:
            if item.kind == CHECK_KIND_CHECK:
                on = action.habit_op == "mark"
                check.set_entry(db, user_id, item.id, CheckEntryBody(done=on))
                done_lines.append(f"'{item.name}' {'체크했어요' if on else '체크를 취소했어요'}")
            else:
                now = (log.count or 0) if log else 0
                delta = action.amount if action.habit_op == "mark" else -action.amount
                new = min(max(now + delta, 0), CHECK_COUNT_MAX)
                check.set_entry(db, user_id, item.id, CheckEntryBody(count=new))
                done_lines.append(f"'{item.name}' {new}/{item.goal}{item.unit or ''}로 기록했어요")
        except ApiError:
            continue
    if not done_lines:
        return AgentResponse(intent="habit", text=NOT_FOUND_TEXT)
    return AgentResponse(intent="habit", text="\n".join(done_lines))
