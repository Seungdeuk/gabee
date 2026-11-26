// "확인이 필요한 사진"의 순수 함수·문구·상태 전이(화면·네트워크와 분리해 시험한다). 사진 내용·대화 글자는 어디에도 기록하지 않는다.
// 서버가 최종 판단한다(앱에서 숨기거나 막는 것만으로 안전하다고 보지 않는다): 업로더 본인·가족 전체방·문서가 아닌 사진만 일반 사진으로 확인된다.

export const REVIEW_ENTRY_KEY = "photochecks";
export const REVIEW_TITLE = "확인이 필요한 사진";
export const REVIEW_EMPTY = "확인이 필요한 사진이 없어요";
export const REVIEW_LOAD_FAILED = "확인이 필요한 사진을 불러오지 못했어요. 잠시 후 다시 해 주세요";

export const SHEET_NOTICE_TITLE = "일반 사진으로 확인할까요?";
export const SHEET_NOTICE_BODY =
  "일반 사진으로 확인하면 우리 가족 타임라인에 보일 수 있어요. 문서·카드·서류·화면 캡처가 찍혀 있다면 확인하지 마세요. 확인한 뒤에는 앱에서 되돌릴 수 없어요.";
export const ACK_LABEL = "문서나 개인정보가 찍힌 사진이 아니라는 것을 확인했어요";
export const CONFIRM_LABEL = "일반 사진이에요";
export const CONFIRMING_LABEL = "확인하는 중…";
export const LATER_LABEL = "나중에";
export const CONFIRMED_NOTICE = "일반 사진으로 확인했어요";

export const DOC_SAVE_HINT = "문서나 서류가 찍힌 사진이면 '문서로 저장'을 눌러 가족 문서함에 넣어 주세요. 문서 사진은 타임라인에 나오지 않아요.";
export const DOC_NOT_REGISTERED = "아직 문서함에서 확인되지 않았어요. 조금 뒤에 다시 저장해 주세요"; // 등록이 오래 걸리는 중일 수도 있어 "없다"고 단정하지 않는다
export const DOC_REGISTERED = "가족 문서함에 저장됐어요";
export const DOC_CHECKING = "문서함에 저장됐는지 확인하는 중…";

// 타임라인에서 뺀 사진 목록(`kind=excluded`)과 다시 넣기: 타임라인 표시에만 영향을 주고 문서함·채팅 원본은 바뀌지 않는다.
export const EXCLUDED_TITLE = "타임라인에서 뺀 사진";
export const EXCLUDED_EMPTY = "타임라인에서 뺀 사진이 없어요";
export const EXCLUDED_ENTRY_LABEL = "뺀 사진";
export const EXCLUDED_SHEET_TITLE = "다시 타임라인에 넣을까요?";
export const EXCLUDED_SHEET_BODY =
  "다시 넣으면 우리 가족 타임라인에 보여요. 채팅방의 사진과 문서함은 그대로예요. 문서·카드·서류·화면 캡처가 찍혀 있다면 넣지 마세요. 언제든 다시 뺄 수 있어요.";
export const INCLUDE_LABEL = "다시 넣기";
export const INCLUDING_LABEL = "넣는 중…";
export const INCLUDED_NOTICE = "타임라인에 다시 넣었어요";

/**
 * 화면 종류: 라우트 값 `excluded` 면 "뺀 사진" 목록, 그 밖(없음·모르는 값)은 기존 "확인이 필요한 사진".
 * @param {unknown} param 라우트 쿼리 값
 * @returns {"review" | "excluded"}
 */
export const reviewKindOf = (param) => (param === "excluded" ? "excluded" : "review");

/** 상태 라벨: 서버는 이 목록의 상태만 돌려준다(unsure·failed, 올린 지 15분 넘은 pending, 뺀 사진 목록의 excluded). */
const STATUS_LABEL = { unsure: "확인 필요", failed: "판별 실패", pending: "처리 지연", excluded: "뺀 사진" };

/**
 * @param {string} status 서버의 판별 상태
 * @returns {string} 목록·시트에 보일 상태 글자(모르는 상태도 "확인 필요"로 둔다)
 */
export const statusLabel = (status) => STATUS_LABEL[status] ?? "확인 필요";

/**
 * 격자 칸의 라벨(눈에 보이는 글자와 접근성 라벨이 같다). 문서함 저장을 시작한 사진은 서버에서는 이미 문서 상태라, 원래 상태 대신 저장 진행을 말한다.
 * @param {{ status: string }} item
 * @param {"checking" | "not_registered" | null | undefined} docState
 * @returns {string}
 */
export const cellLabel = (item, docState) => (docState === "not_registered" ? "저장 확인 필요" : docState === "checking" ? "저장 확인 중" : statusLabel(item?.status));

/**
 * 서랍의 진입 행 제목. 개수를 모르거나 0이면 행 자체를 만들지 않으므로(buildDrawerSections) 1 이상일 때만 쓴다.
 * @param {number} count
 * @returns {string}
 */
export const reviewRowTitle = (count) => `${REVIEW_TITLE} ${count}장`;

/**
 * 서랍에 진입 행을 보일 개수인가: 양의 정수만(0·음수·모름·숫자가 아닌 값은 보이지 않는다).
 * @param {unknown} count
 * @returns {boolean}
 */
export const shouldShowReviewRow = (count) => Number.isInteger(count) && count > 0;

/**
 * "일반 사진이에요" 버튼을 누를 수 있는가: 안내 확인란을 체크했고 처리 중이 아닐 때만.
 * @param {{ acknowledged: boolean, busy: boolean }} state
 * @returns {boolean}
 */
export const canConfirm = ({ acknowledged, busy }) => acknowledged === true && !busy;

/**
 * 목록에서 한 장을 뺀다(원본은 바꾸지 않는다).
 * @param {{ attachment_id: string }[]} items
 * @param {string} id
 * @returns {{ attachment_id: string }[]}
 */
export const removeItem = (items, id) => (items ?? []).filter((it) => it.attachment_id !== id);

const WAIT = (seconds) => (seconds < 60 ? `${seconds}초` : `${Math.ceil(seconds / 60)}분`);

const BY_CODE = {
  document_to_photo_blocked: "문서로 판단됐거나 문서함에 저장된 사진은 일반 사진으로 바꿀 수 없어요",
  check_in_progress: "사진을 확인하는 중이에요. 잠시 후에 다시 해 주세요",
  photo_checks_unavailable: "지금은 사진 확인 상태를 불러오지 못해요. 잠시 후 다시 해 주세요",
  not_found: "이 사진은 확인할 수 없어요. 이미 지워졌거나 내가 올린 사진이 아니에요",
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/**
 * 확인·목록 조회 오류(ApiError)를 사용자 문구로. 서버 문구는 그대로 쓰지 않는다(내부 사정이 보이지 않게). 대화·사진 내용은 문장에 넣지 않는다.
 * @param {{ code?: string, status?: number, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function photoCheckErrorMessage(error) {
  if (!error) return "";
  if (error.code === "too_many_checks" || error.status === 429) {
    const wait = error.retryAfter ? ` (${WAIT(error.retryAfter)} 뒤에 다시 할 수 있어요)` : "";
    return `요청이 너무 잦아요. 잠시 후 다시 해 주세요${wait}`;
  }
  if (error.status === 404) return BY_CODE.not_found;
  return BY_CODE[error.code] ?? "요청을 처리하지 못했어요. 잠시 후 다시 해 주세요";
}

/**
 * 이 오류는 "이 사진은 더 이상 확인 대상이 아님"(지워졌거나 내 사진이 아니거나 이미 문서)이라 목록에서 빼도 되는가.
 * 일시 오류(503·429·네트워크)는 목록에 남긴다.
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {boolean}
 */
export const isGoneError = (error) => error?.status === 404 || error?.code === "document_to_photo_blocked";

// ---------------------------------------------------------------------------------------------
// 목록 상태(번호(seq)가 다른 옛 응답은 버린다 — 화면을 떠났다 돌아오거나 다시 시도할 때 섞이지 않게)

/** @returns {{ seq: number, status: "loading" | "ready" | "error", items: object[], total: number, next: number | null, error: string, loadingMore: boolean }} */
export const initialReviewState = () => ({ seq: 0, status: "loading", items: [], total: 0, next: null, error: "", loadingMore: false });

/**
 * @param {ReturnType<typeof initialReviewState>} state
 * @param {{ type: string, seq?: number, page?: { items?: object[], needs_review_count?: number, next_before?: number | null }, error?: { code?: string, status?: number, retryAfter?: number }, id?: string }} action
 * @returns {ReturnType<typeof initialReviewState>}
 */
export function reviewReducer(state, action) {
  switch (action.type) {
    case "start":
      return { ...initialReviewState(), seq: action.seq };
    case "firstOk":
      if (action.seq !== state.seq) return state;
      return {
        ...state,
        status: "ready",
        items: action.page?.items ?? [],
        total: Number.isInteger(action.page?.needs_review_count) ? action.page.needs_review_count : (action.page?.items ?? []).length,
        next: action.page?.next_before ?? null,
        error: "",
      };
    case "firstFail":
      if (action.seq !== state.seq) return state;
      return { ...state, status: "error", error: photoCheckErrorMessage(action.error) || REVIEW_LOAD_FAILED };
    case "moreStart":
      if (action.seq !== state.seq) return state;
      return { ...state, loadingMore: true, error: "" };
    case "moreOk": {
      if (action.seq !== state.seq) return state;
      const seen = new Set(state.items.map((it) => it.attachment_id));
      const added = (action.page?.items ?? []).filter((it) => !seen.has(it.attachment_id)); // 쪽 사이에 겹친 사진은 한 번만
      return {
        ...state,
        loadingMore: false,
        items: [...state.items, ...added],
        total: Number.isInteger(action.page?.needs_review_count) ? action.page.needs_review_count : state.total,
        next: action.page?.next_before ?? null,
      };
    }
    case "moreFail":
      if (action.seq !== state.seq) return state;
      return { ...state, loadingMore: false, error: photoCheckErrorMessage(action.error) || REVIEW_LOAD_FAILED };
    case "removed": {
      // 확인했거나 문서로 저장해 더 이상 확인이 필요 없는 사진: 목록과 개수에서 한 번만 뺀다(목록에 없으면 개수도 건드리지 않는다)
      if (!state.items.some((it) => it.attachment_id === action.id)) return state;
      return { ...state, items: removeItem(state.items, action.id), total: Math.max(0, state.total - 1) };
    }
    default:
      return state;
  }
}

/**
 * 화면이 무엇을 보여 줄지. 보이는 사진을 모두 처리해 목록이 비어도 서버에 더 남은 쪽(next)이 있으면 "없어요"가 아니라 계속 불러오거나(more) 오류와 다시 시도(more_error)를 보인다
 * — 다음 쪽 조회 실패를 빈 목록(확인할 사진 없음)으로 보이지 않는다.
 * @param {ReturnType<typeof initialReviewState>} state
 * @returns {"loading" | "error" | "grid" | "more" | "more_error" | "empty"}
 */
export function reviewBodyKind(state) {
  if (state.status === "loading") return "loading";
  if (state.status === "error") return "error";
  if (state.items.length > 0) return "grid";
  if (state.next != null) return state.error ? "more_error" : "more";
  return "empty";
}

/** @param {ReturnType<typeof initialReviewState>} state 다음 쪽을 부를 수 있는가(이전 쪽이 실패해 error 가 남아 있어도 "다시 시도" 버튼으로는 부를 수 있다. 자동으로 계속 부르지 않는 것은 격자가 error 를 보고 막는다) */
export const canLoadMoreReview = (state) => state.status === "ready" && state.next != null && !state.loadingMore;

// ---------------------------------------------------------------------------------------------
// 문서로 저장 → 실제 등록 확인(성공으로 보이지 않게: 등록 여부를 다시 물어 확인한다)

/**
 * "일반 사진이에요"를 누른 뒤의 흐름(화면과 분리해 시험한다). 확인란을 체크하지 않았거나, 처리 중이거나, 같은 사진이 이미 처리 중이면 서버를 부르지 않는다.
 * 같은 사진을 두 번 눌러도 요청은 한 번만 나간다(working 은 처리 중인 사진 id 집합이고 끝나면 반드시 비운다).
 * @param {{ id: string | undefined, acknowledged: boolean, busy: null | string, working: Set<string>, confirm: (id: string) => Promise<unknown> }} args
 * @returns {Promise<{ kind: "skipped" } | { kind: "confirmed" | "gone" | "failed", message: string }>} gone 은 더 이상 확인 대상이 아님(목록에서 뺀다), failed 는 일시 오류(시트를 열어 둔 채 다시 시도)
 */
export async function runConfirm({ id, acknowledged, busy, working, confirm }) {
  if (!id || !canConfirm({ acknowledged, busy: busy != null }) || working.has(id)) return { kind: "skipped" };
  working.add(id);
  try {
    await confirm(id);
    return { kind: "confirmed", message: CONFIRMED_NOTICE };
  } catch (e) {
    return { kind: isGoneError(e) ? "gone" : "failed", message: photoCheckErrorMessage(e) };
  } finally {
    working.delete(id);
  }
}

export const LIBRARY_POLL_DELAYS_MS = [3000, 10000, 30000];

/**
 * 문서함 저장을 시작한 뒤 등록됐는지 정해진 간격으로 확인한다. 한 번이라도 registered 면 그 즉시 끝낸다.
 * 끝까지 not_registered 이거나 확인이 계속 실패하면 "registered" 가 아니다(거짓 성공을 만들지 않는다).
 * @param {(id: string) => Promise<{ state: string }>} getState 등록 여부 조회
 * @param {string} id 사진 첨부 id
 * @param {{ delays?: number[], sleep?: (ms: number) => Promise<void>, shouldStop?: () => boolean }} [deps] 시험용
 * @returns {Promise<"registered" | "not_registered" | "stopped">}
 */
export async function waitUntilRegistered(getState, id, deps = {}) {
  const delays = deps.delays ?? LIBRARY_POLL_DELAYS_MS;
  const sleep = deps.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  for (const delay of delays) {
    await sleep(delay);
    if (deps.shouldStop?.()) return "stopped";
    try {
      const res = await getState(id);
      if (res?.state === "registered") return "registered";
    } catch {
      // 한 번 못 물어봐도 다음 간격에 다시 묻는다(실패를 등록으로 보지 않는다)
    }
  }
  return "not_registered";
}

/**
 * "문서로 저장" 흐름: 저장을 시작하고(성공해야만) 실제 등록을 다시 확인한다. 저장을 시작하지 못하면 확인하지 않고 그 문구를 돌려준다.
 * 등록이 확인되기 전에는 성공(registered)이라고 하지 않는다. 같은 사진이 이미 처리 중이거나 다른 처리 중이면 서버를 부르지 않는다.
 * @param {{ id: string | undefined, busy: null | string, working: Set<string>, save: (attachment: { id: string }) => Promise<{ ok: boolean, message: string }>, getState: (id: string) => Promise<{ state: string }>, onQueued?: () => void, shouldStop?: () => boolean, delays?: number[], sleep?: (ms: number) => Promise<void> }} args
 * @returns {Promise<{ kind: "skipped" } | { kind: "save_failed", message: string } | { kind: "registered" | "not_registered" | "stopped", message: string }>}
 */
export async function runDocumentSave({ id, busy, working, save, getState, onQueued, shouldStop, delays, sleep }) {
  if (!id || busy != null || working.has(id)) return { kind: "skipped" };
  working.add(id);
  try {
    const saved = await save({ id });
    if (!saved?.ok) return { kind: "save_failed", message: saved?.message ?? "" };
    onQueued?.();
    const result = await waitUntilRegistered(getState, id, { shouldStop, delays, sleep });
    const message = result === "registered" ? DOC_REGISTERED : result === "not_registered" ? DOC_NOT_REGISTERED : "";
    return { kind: result, message };
  } finally {
    working.delete(id);
  }
}
