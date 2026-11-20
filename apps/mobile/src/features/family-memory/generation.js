// 사용자 요청형 추억 생성(PR10)의 순수 로직: 상태 문구·표시 결정·오류 변환·진행 확인(폴링) 규칙. 화면·훅과 분리해 node 시험으로 확인한다.

export const GENERATION_POLL_MS = 5000; // 처리 중일 때 같은 요청(멱등)을 다시 보내 진행을 확인하는 간격
export const GENERATION_POLL_MAX = 120; // 한 번의 "추억 만들기"에서 진행을 확인하는 최대 횟수(약 10분). 넘으면 멈추고 사용자가 다시 누르게 한다

export const GENERATION_LABELS = {
  create: "추억 만들기",
  recheck: "다시 확인하기",
  needsConsent: "먼저 내 사진 분석에 동의해 주세요",
  failed: "일부 사진을 분석하지 못했어요. 잠시 뒤 다시 확인해 주세요",
  closed: "추억 만들기는 아직 열려 있지 않아요",
  stalled: "시간이 걸리고 있어요. 잠시 뒤 '다시 확인하기'를 눌러 주세요",
};

/**
 * 서버 진행 상태를 화면에 보일 모양으로 바꾼다. 반환값의 button 이 null 이면 누를 수 있는 버튼이 없다.
 * @param {{ state: string, eligible: number, embedded: number, processing: number, failed: number, candidates: number } | null | undefined} gen
 * @param {{ polling?: boolean, busy?: boolean }} [options] polling: 진행을 확인하는 중, busy: 요청을 보내는 중
 * @returns {{ visible: boolean, kind: string, text: string, button: "create" | "recheck" | null, spinner: boolean }}
 */
export function generationView(gen, { polling = false, busy = false } = {}) {
  if (!gen || typeof gen.state !== "string") return { visible: false, kind: "hidden", text: "", button: null, spinner: false };
  switch (gen.state) {
    case "needs_consent":
      return { visible: true, kind: "needs_consent", text: GENERATION_LABELS.needsConsent, button: null, spinner: false };
    case "not_enough_photos":
      return { visible: true, kind: "not_enough_photos", text: `사진이 3장 이상 모이면 만들 수 있어요 (지금 ${gen.eligible}장)`, button: null, spinner: false };
    case "processing":
      return { visible: true, kind: "processing", text: `사진을 살펴보는 중이에요 (${gen.embedded}/${gen.eligible}장)`, button: null, spinner: true };
    case "ready":
      return {
        visible: true,
        kind: "ready",
        text: gen.candidates > 0 ? `추억 후보 ${gen.candidates}개를 찾았어요` : "묶을 만한 추억을 아직 찾지 못했어요",
        button: busy || polling ? null : "recheck",
        spinner: busy || polling,
      };
    case "failed":
      return { visible: true, kind: "failed", text: GENERATION_LABELS.failed, button: null, spinner: false };
    case "idle":
      return { visible: true, kind: "idle", text: `사진 ${gen.eligible}장으로 추억 후보를 만들 수 있어요`, button: busy ? null : "create", spinner: busy };
    default:
      return { visible: false, kind: "hidden", text: "", button: null, spinner: false };
  }
}

/**
 * 생성 요청·조회 오류를 화면 문구로 바꾼다. 404(꺼져 있음)·403 generation_not_open 은 패널 자체를 숨긴다(hidden).
 * @param {{ status?: number, code?: string } | null | undefined} error ApiError
 * @returns {{ hidden: boolean, message: string }}
 */
export function generationError(error) {
  const status = error?.status;
  const code = error?.code;
  if (status === 404 || code === "generation_not_open") return { hidden: true, message: GENERATION_LABELS.closed };
  if (code === "consent_required") return { hidden: false, message: GENERATION_LABELS.needsConsent };
  if (code === "family_off" || code === "memory_disabled") return { hidden: false, message: "가족 AI 추억 기능이 켜져 있지 않아요" };
  if (status === 401) return { hidden: false, message: "로그인이 만료됐어요. 다시 로그인해 주세요" };
  if (status === 0) return { hidden: false, message: "서버에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요" };
  return { hidden: false, message: "추억 만들기를 진행하지 못했어요. 잠시 뒤 다시 시도해 주세요" };
}

/**
 * 진행 확인을 이어갈지 정한다: 처리 중이고 최대 횟수 전일 때만 이어간다.
 * @param {{ state?: string } | null | undefined} gen
 * @param {number} polls 지금까지 확인한 횟수
 * @returns {boolean}
 */
export const shouldKeepPolling = (gen, polls) => gen?.state === "processing" && polls < GENERATION_POLL_MAX;

/**
 * 상태가 바뀌어 후보 목록을 다시 불러와야 하는가(후보 수가 달라졌거나 처리 중에서 준비로 바뀜).
 * @param {{ state?: string, candidates?: number } | null | undefined} prev
 * @param {{ state?: string, candidates?: number } | null | undefined} next
 * @param {boolean} [explicit] 사용자가 직접 "추억 만들기/다시 확인하기"를 눌렀는가. 철회·삭제로 후보 수는 그대로인데 사진만 줄 수 있어, 직접 누르면 ready 에서 늘 다시 불러온다
 * @returns {boolean}
 */
export function shouldReloadCandidates(prev, next, explicit = false) {
  if (!next || next.state !== "ready") return false;
  if (explicit) return true;
  return !prev || prev.state !== "ready" || prev.candidates !== next.candidates;
}

export const initialGenerationState = () => ({ scope: null, seq: 0, gen: null, hidden: false, error: null, busy: false });

/**
 * 생성 상태 전이. 범위(사용자·가족)가 바뀌거나 로그아웃하면 이전 가족의 상태를 **즉시 비운다**. 늦게 온 응답(seq 불일치)은 버린다.
 * action: { type: "scope", scope, seq } | { type: "start", seq } | { type: "ok", seq, gen } | { type: "fail", seq, error }
 * @param {ReturnType<typeof initialGenerationState>} state
 * @param {{ type: string, seq?: number, scope?: string | null, gen?: object, error?: object }} action
 * @returns {ReturnType<typeof initialGenerationState>}
 */
export function generationReducer(state, action) {
  switch (action.type) {
    case "scope":
      return { ...initialGenerationState(), scope: action.scope, seq: action.seq };
    case "start":
      return action.seq === state.seq ? { ...state, busy: true, error: null } : state;
    case "ok":
      return action.seq === state.seq ? { ...state, busy: false, gen: action.gen, hidden: false, error: null } : state;
    case "fail": {
      if (action.seq !== state.seq) return state;
      const e = generationError(action.error);
      return { ...state, busy: false, hidden: e.hidden, error: e.hidden ? null : e.message };
    }
    default:
      return state;
  }
}