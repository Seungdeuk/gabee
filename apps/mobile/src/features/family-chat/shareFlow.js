/**
 * 공유 카드 보내기 화면 흐름(공유 시트 → 확인창 → 전송)의 상태 전이 순수 함수. 타이머·네트워크는 훅(useChatShare)이 맡고 여기에는 "다음 상태"만 있다.
 * 지키는 규칙: 시트와 확인창은 동시에 열리지 않고(겹치면 iOS 에서 열리지 않는 경우가 있다), 고르면 시트를 닫은 뒤 훅이 대기하고 나서 showConfirm 을 보내야 확인창이 열리며,
 * 늦게 온 목록 응답은 요청 번호(token)가 다르거나 닫은 뒤면 버리고, 확인은 한 번만 통한다. 닫아도 종류·항목·선택은 남겨 닫히는 동안 제목·문구가 비지 않는다.
 * 일정 제목·금액은 어디에도 기록하지 않는다.
 */

/**
 * @typedef {{ kind: "event" | "settlement" | null, status: "idle" | "loading" | "ready" | "error", items: object[], error: string, sheetOpen: boolean, confirmOpen: boolean, pending: object | null, token: number | null }} ShareFlowState
 */

/** 아직 아무것도 열지 않은 처음 상태. @type {ShareFlowState} */
export const SHARE_FLOW_IDLE = { kind: null, status: "idle", items: [], error: "", sheetOpen: false, confirmOpen: false, pending: null, token: null };

/**
 * 다음 상태. 맞지 않는 때(가드)는 같은 state 객체를 그대로 돌려준다.
 * - open: 시트를 연다(이전 선택·확인창은 비운다). 정산은 items 를 바로 받고 일정은 불러오는 중(token 이 이 요청의 번호)으로 시작한다.
 * - loaded·failed: 같은 token 의 목록 응답만 반영한다.
 * - close: 시트(와 확인창)를 닫는다. token 을 무효로 만들어 늦은 응답을 버린다.
 * - pick: 항목을 고르면 시트를 닫고 항목을 기억한다(확인창은 열지 않는다).
 * - showConfirm: 시트가 닫힌 뒤(대기 후) 확인창을 연다. 고른 항목이 없거나 시트가 열려 있으면 무시한다.
 * - cancelPending: 확인창이 열려 있을 때만 닫는다(목록·선택은 남긴다).
 * - reopenSheet: 확인창에서 취소한 뒤 대기 후 시트를 다시 연다. 확인창이 떠 있거나 종류가 없으면 무시한다.
 * - confirm: 확인창이 열려 있을 때만 닫는다(두 번째는 무시, 선택은 남긴다).
 * @param {ShareFlowState} state
 * @param {{ type: "open", kind: "event" | "settlement", token: number, items?: object[] } | { type: "loaded", token: number, items: object[] } | { type: "failed", token: number, error: string } | { type: "close" } | { type: "pick", item: object } | { type: "showConfirm" } | { type: "cancelPending" } | { type: "reopenSheet" } | { type: "confirm" }} action
 * @returns {ShareFlowState}
 */
export function shareFlowReducer(state, action) {
  switch (action.type) {
    case "open":
      return action.kind === "settlement"
        ? { ...SHARE_FLOW_IDLE, kind: action.kind, status: "ready", items: action.items ?? [], sheetOpen: true, token: action.token }
        : { ...SHARE_FLOW_IDLE, kind: action.kind, status: "loading", sheetOpen: true, token: action.token };
    case "loaded":
      return action.token === state.token ? { ...state, status: "ready", items: action.items, error: "" } : state;
    case "failed":
      return action.token === state.token ? { ...state, status: "error", items: [], error: action.error } : state;
    case "close":
      return { ...state, sheetOpen: false, confirmOpen: false, token: null };
    case "pick":
      return { ...state, pending: action.item, sheetOpen: false, confirmOpen: false };
    case "showConfirm":
      return state.pending && state.kind && !state.sheetOpen ? { ...state, confirmOpen: true } : state;
    case "cancelPending":
    case "confirm":
      return state.confirmOpen ? { ...state, confirmOpen: false } : state;
    case "reopenSheet":
      return state.kind && !state.sheetOpen && !state.confirmOpen ? { ...state, sheetOpen: true } : state;
    default:
      return state;
  }
}
