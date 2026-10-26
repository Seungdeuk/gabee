// 과거 창(검색 결과로 이동) ↔ 라이브 전환의 순수 규칙(훅과 분리해 시험한다). 대화 글자는 다루지 않고 모드·세대 번호만 다룬다.
import { mergeMessages } from "./chatUtils";

/**
 * 처음 모드. initialFocus 가 있으면 처음부터 과거 모드다.
 * @param {number | null | undefined} initialFocus
 * @returns {{ mode: "live" | "past", gen: number, busy: null | "focus" | "live" }}
 */
export const initialModeState = (initialFocus) => ({ mode: initialFocus != null ? "past" : "live", gen: 0, busy: null });

/**
 * 창을 바꾸는 요청(focus: 과거 창 불러오기, live: 라이브 복귀)을 시작한다. 세대 번호가 올라가 그 전에 시작한 요청의 응답은 버려진다.
 * @param {{ mode: string, gen: number, busy: string | null }} state
 * @param {"focus" | "live"} kind
 * @returns {{ mode: "live" | "past", gen: number, busy: "focus" | "live" }}
 */
export const beginTransition = (state, kind) => ({ mode: kind === "focus" ? "past" : state.mode, gen: state.gen + 1, busy: kind });

/**
 * 창을 바꾸는 요청이 끝났을 때. 세대 번호가 다르면(그 사이 새 전환이 시작됨) 적용하지 않는다.
 * 라이브 복귀 성공만 모드를 live 로 바꾼다. 실패하거나 focus 요청이면 모드는 그대로이고 busy 만 풀린다.
 * @param {{ mode: string, gen: number, busy: string | null }} state
 * @param {number} gen 요청을 시작할 때의 세대 번호
 * @param {"focus" | "live"} kind
 * @param {boolean} ok
 * @returns {{ state: object, applied: boolean }}
 */
export function finishTransition(state, gen, kind, ok) {
  if (gen !== state.gen) return { state, applied: false };
  return { state: { mode: kind === "live" && ok ? "live" : state.mode, gen: state.gen, busy: null }, applied: true };
}

/** 과거 창 아래 끝이 라이브 끝에 닿아 자동으로 라이브가 된다(세대 번호는 그대로). */
export const enterLiveEnd = (state) => ({ ...state, mode: "live" });

/** 새 메시지 확인(폴링)을 해도 되는지: 라이브이고 창을 바꾸는 중이 아닐 때. */
export const canPoll = (state) => state.mode === "live" && !state.busy;

/** 위로 더 불러와도 되는지: 창을 바꾸는 중이 아닐 때. */
export const canLoadOlder = (state) => !state.busy;

/** 아래로 더 불러와도 되는지: 과거 창이고 창을 바꾸는 중이 아닐 때. */
export const canLoadNewer = (state) => state.mode === "past" && !state.busy;

/**
 * 요청을 보낼 때 기억해 두는 표.
 * @param {{ mode: string, gen: number }} state
 * @returns {{ gen: number, mode: string }}
 */
export const windowToken = (state) => ({ gen: state.gen, mode: state.mode });

/** 응답이 왔을 때 그 사이 모드·세대가 바뀌지 않았는지. 바뀌었으면 응답을 버린다. */
export const tokenValid = (state, token) => state.gen === token.gen && state.mode === token.mode;

/** 글·사진·재전송 전에 라이브로 돌아가야 하는지(과거 창이거나 창을 바꾸는 중). 돌아가지 못하면 보내지 않는다. */
export const needsLiveBeforeSend = (state) => state.mode === "past" || state.busy !== null;

/**
 * 서버가 저장했다고 돌려준 메시지를 목록에 반영한다. 임시 메시지(clientId)는 지우고, 라이브일 때만 서버 메시지를 병합한다.
 * 과거 창에는 병합하지 않는다(최신 id 가 창에 끼면 이후 loadNewer 가 그 id 부터 받아 중간 대화가 빠진다) — 라이브로 돌아오면 목록에서 받는다.
 * @param {object[]} list
 * @param {object} saved
 * @param {"live" | "past"} mode 저장이 끝난 시점의 모드
 * @param {string | null} [clientId]
 * @returns {object[]}
 */
export function applySaved(list, saved, mode, clientId = null) {
  const base = clientId ? list.filter((m) => m.clientId !== clientId) : list;
  return mode === "past" ? base : mergeMessages(base, [saved]);
}

/**
 * 오류 배너의 "다시 시도"가 할 일. 라이브면 새 메시지 확인, 과거 창이면 마지막에 실패한 동작(위/아래 불러오기)이나 라이브 복귀.
 * @param {string | null} lastFail "older" | "newer" | "focus" | "live" | null
 * @param {{ mode: string }} state
 * @returns {"poll" | "older" | "newer" | "live"}
 */
export function retryTarget(lastFail, state) {
  if (state.mode !== "past") return "poll";
  if (lastFail === "older" || lastFail === "newer") return lastFail;
  return "live";
}

/**
 * 진행 중인 라이브 복귀 요청을 다시 쓸 수 있는지: 시작 때의 세대가 지금과 같고 아직 복귀 전환 중일 때만.
 * 그 사이 다른 전환(검색 결과 이동 등)이 시작돼 세대가 올라갔으면 그 요청은 이미 무효라 새로 시작해야 한다.
 * @param {{ gen: number } | null | undefined} run 진행 중 요청(시작 때의 세대)
 * @param {{ gen: number, busy: string | null }} state
 * @returns {boolean}
 */
export const canReuseLiveRun = (run, state) => Boolean(run) && run.gen === state.gen && state.busy === "live";

/**
 * 저장이 끝난 시점의 모드로 서버 메시지를 목록에 반영한다(applySaved 에 현재 상태를 연결하는 얇은 헬퍼).
 * @param {object[]} list
 * @param {object} saved
 * @param {{ mode: "live" | "past" }} state 저장이 끝난 시점의 모드 상태
 * @param {string | null} [clientId]
 * @returns {object[]}
 */
export const applySavedNow = (list, saved, state, clientId = null) => applySaved(list, saved, state.mode, clientId);
