// 채팅의 확인 카드: 일정(가족 공유 등록·수정·삭제)과 정산·돌봄 쓰기 제안(지출·식단·돌봄 기록). 서버 응답 변환, 버튼, 결과 문구(순수 함수, 시험: tests/scheduleconfirm.test.js)
// 서버는 일정 요청을 채팅에서 바로 실행하지 않고 카드(confirm_cards)로 돌려준다. 사용자가 버튼을 누르면 앱이 기존
// POST /schedule/agent/confirm 에 { action: pending_action, share } 를 보내 실행한다(AI 를 부르지 않고, 서버는 돌려받은 내용을 다시 검증한다).
// 정산·돌봄 에이전트의 쓰기 제안은 응답의 proposals([{ token, summary, tab }])로 오고, 버튼을 누르면 POST /<tab>/agent/confirm { token } 으로 실행한다.

export const CARD_PENDING = "pending";
export const CARD_DONE = "done";
export const CARD_CANCELLED = "cancelled";
export const CANCELLED_TEXT = "취소했어요. 아무것도 바뀌지 않았어요.";

/**
 * 서버의 confirm_cards 를 앱이 쓰는 모양으로 바꾼다. 모르는 종류는 버린다(눌러서 실행할 수 없는 카드는 보이지 않게).
 * @param {any[] | undefined | null} cards
 * @returns {{ kind: "schedule", action: "register" | "edit" | "delete", title: string, lines: string[], sharedWith: string[], pendingAction: object, status: string, resultText: string }[]}
 */
export function mapConfirmCards(cards) {
  return (Array.isArray(cards) ? cards : [])
    .filter((c) => c && c.kind === "schedule" && ["register", "edit", "delete"].includes(c.action) && c.pending_action && typeof c.pending_action === "object")
    .map((c) => ({
      kind: "schedule",
      action: c.action,
      title: String(c.title ?? ""),
      lines: Array.isArray(c.lines) ? c.lines.map(String) : [],
      sharedWith: Array.isArray(c.shared_with) ? c.shared_with.map(String) : [],
      pendingAction: c.pending_action,
      status: CARD_PENDING,
      resultText: "",
    }));
}

export const PROPOSAL_TABS = { billing: "정산", care: "돌봄" };

/**
 * 정산·돌봄 에이전트의 쓰기 제안(proposals)을 카드로 바꾼다. 모르는 탭이나 토큰이 없는 제안은 버린다(누르면 실행되는 것만 보인다).
 * 요약문(summary)은 서버가 검증된 값으로 만든 문장이라 그대로 보여 준다.
 * @param {{ token?: string, summary?: string, tab?: string }[] | undefined | null} proposals
 * @returns {{ kind: "proposal", action: "propose", tab: "billing" | "care", title: string, lines: string[], sharedWith: string[], token: string, status: string, resultText: string }[]}
 */
export function mapProposals(proposals) {
  return (Array.isArray(proposals) ? proposals : [])
    .filter((p) => p && typeof p.token === "string" && p.token && Object.hasOwn(PROPOSAL_TABS, p.tab))
    .map((p) => ({
      kind: "proposal",
      action: "propose",
      tab: p.tab,
      title: `${PROPOSAL_TABS[p.tab]} 에이전트의 제안`,
      lines: [String(p.summary ?? "")].filter(Boolean),
      sharedWith: [],
      token: p.token,
      status: CARD_PENDING,
      resultText: "",
    }));
}

/**
 * 채팅 응답(/ai-assistant/chat)에서 확인이 필요한 카드를 모두 모은다: 일정 카드 먼저, 그다음 정산·돌봄 제안.
 * @param {{ confirm_cards?: any[], proposals?: any[] } | null | undefined} res
 */
export function mapChatCards(res) {
  return [...mapConfirmCards(res?.confirm_cards), ...mapProposals(res?.proposals)];
}

/**
 * 카드의 버튼. share 는 등록일 때 서버에 보내는 값(true: 공유 대상에게도 등록, false: 내 일정만).
 * @param {{ action: string, sharedWith: string[] }} card
 * @returns {{ key: string, label: string, share?: boolean, tone: "main" | "ghost" | "danger" }[]}
 */
export function cardButtons(card) {
  if (card.kind === "proposal") {
    return [
      { key: "ok", label: "확인", share: false, tone: "main" },
      { key: "cancel", label: "취소", tone: "ghost" },
    ];
  }
  if (card.action === "register") {
    return card.sharedWith.length > 0
      ? [
          { key: "share", label: "공유해서 등록", share: true, tone: "main" },
          { key: "mine", label: "나만 등록", share: false, tone: "ghost" },
          { key: "cancel", label: "취소", tone: "ghost" },
        ]
      : [
          { key: "mine", label: "등록", share: false, tone: "main" },
          { key: "cancel", label: "취소", tone: "ghost" },
        ];
  }
  if (card.action === "delete") {
    return [
      { key: "ok", label: "삭제", share: false, tone: "danger" },
      { key: "cancel", label: "취소", tone: "ghost" },
    ];
  }
  return [
    { key: "ok", label: "바꾸기", share: false, tone: "main" },
    { key: "cancel", label: "취소", tone: "ghost" },
  ];
}

/**
 * 확인 요청의 응답(AgentResponse)에서 사용자에게 보여 줄 한 줄. 등록 카드가 있으면 공유한 사람 수를 덧붙인다.
 * @param {{ text?: string, cards?: { type: string, data?: object }[] } | null | undefined} res
 * @returns {string}
 */
export function confirmResultText(res) {
  const base = String(res?.text ?? "").trim() || "반영했어요.";
  const registered = (res?.cards ?? []).find((c) => c.type === "registered");
  const shared = Number(registered?.data?.shared ?? 0);
  return shared > 0 ? `${base} (가족 ${shared}명에게도 공유했어요)` : base;
}
