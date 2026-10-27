// 일정 에이전트 서버 응답(/schedule/agent)을 채팅 말풍선 필드로 바꾸는 순수 함수들. 화면·테마에 의존하지 않아 node 테스트로 확인한다.

/** 답을 만들지 못했을 때의 안내 문장. */
export const ERROR_TEXT = "지금은 답하기 어려워요. 잠시 뒤에 다시 물어봐 주세요";

/** 일정 요청이 아니라고 서버가 돌려줬을 때의 안내 문장(메인 채팅이 생기기 전까지). */
const NOT_SCHEDULE_TEXT = "아직 그건 잘 몰라요. 일정에 대해 물어봐 주세요.";

const CONFIRM_KIND = { register_confirm: "register", edit_confirm: "edit", delete_confirm: "delete" };

/** 카드의 일정 요약(brief)을 미니 카드가 그릴 수 있는 항목으로. 내 목록에 있으면 그 항목(이름표·주제 포함)을 쓴다. */
function briefItem(brief, items) {
  const found = items.find((i) => i.id === brief.id);
  if (found) return { ...found, checked: brief.checked ?? found.checked };
  return {
    id: brief.id,
    kind: "appointment",
    title: brief.title,
    date: brief.date,
    startTime: brief.time || null,
    endTime: brief.end_time || null,
    allDay: false,
    place: "",
    memo: brief.note ?? "",
    whoIds: [],
    topicId: null,
    sharedWith: [],
    createdBy: "me",
    checked: Boolean(brief.checked),
  };
}

/**
 * 서버 에이전트 응답 → 채팅 말풍선 필드(text·items·registered·confirm·draft·pending).
 * 되묻는 응답의 draft 와 확인 카드의 pending 은 다음 요청에 쓰려고 말풍선에 같이 둔다.
 * @param {import("./api").AgentResponse} res
 * @param {import("./model").ScheduleItem[]} items 지금 내 일정
 */
export function fromAgentResponse(res, items) {
  const message = { text: res.text || NOT_SCHEDULE_TEXT };
  for (const card of res.cards ?? []) {
    const d = card.data;
    if (card.type === "event_list") {
      message.items = [...(message.items ?? []), ...d.events.map((e) => briefItem(e, items))];
    } else if (card.type === "registered") {
      message.registered = {
        eventId: d.event_id,
        title: d.title,
        date: d.date,
        startTime: d.start_time || null,
        endTime: d.end_time || null,
        place: d.place ?? "",
        who: d.who ?? [],
        shared: d.shared ?? 0,
      };
    } else if (CONFIRM_KIND[card.type]) {
      message.confirm = { kind: CONFIRM_KIND[card.type], state: "pending" };
      if (d.event) message.confirm.event = d.event;
      if (d.changes)
        message.confirm.lines = d.changes.map((c) =>
          typeof c === "string" ? c : `${c.label} ${c.before} → ${c.after}`,
        );
      if (card.type === "register_confirm") message.confirm.register = d;
    }
  }
  if (res.pending_action) message.pending = res.pending_action;
  if (res.draft) message.draft = res.draft;
  return message;
}

/** 서버 요청이 실패했을 때의 답 말풍선. 한도 초과(429)는 서버 문장을 그대로 보여 준다. */
export function agentErrorMessage(error) {
  return { text: error?.status === 429 && error.message ? error.message : ERROR_TEXT, error: true };
}

/** 이 응답이 내 일정을 바꿨을 수 있나(목록을 다시 읽어야 한다). */
export const changedItems = (res) => ["register", "edit", "delete", "check"].includes(res.intent);
