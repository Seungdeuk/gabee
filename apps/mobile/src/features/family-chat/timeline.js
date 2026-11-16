// 가족 타임라인의 순수 함수·문구·상태 전이(화면·네트워크와 분리해 시험한다). 사진 내용·대화 글자는 어디에도 기록하지 않는다.
// 어떤 사진이 타임라인에 나오는지는 서버가 정한다(일반 사진으로 확인된 가족 전체방 사진만). 앱은 받은 목록을 날짜로 묶어 보일 뿐 숨기거나 더하지 않는다.

import { photoCheckErrorMessage } from "./photoChecks";

export const TIMELINE_ENTRY_KEY = "timeline"; // 서랍의 진입 행 key
export const TIMELINE_TITLE = "가족 타임라인";
export const TIMELINE_EMPTY = "아직 타임라인에 사진이 없어요";
export const TIMELINE_EMPTY_HINT = "가족방에 올린 사진을 일반 사진으로 확인하면 여기에 모여요";
export const TIMELINE_LOAD_FAILED = "타임라인을 불러오지 못했어요. 잠시 후 다시 해 주세요";

export const ORIGINAL_LABEL = "원본 메시지로 가기";
export const EXCLUDE_LABEL = "타임라인에서 빼기";
export const EXCLUDING_LABEL = "빼는 중…";
export const EXCLUDED_NOTICE = "타임라인에서 뺐어요. 채팅방의 사진은 그대로예요";
export const SENT_DAY_NOTE = "보낸 날 기준";
export const UNKNOWN_DAY = "날짜를 알 수 없어요";

export const TIMELINE_COLUMNS = 3;

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 시각(ISO 8601)을 한국 시간 기준 연·월·일로. 읽을 수 없으면 null.
 * @param {unknown} iso
 * @returns {{ y: number, m: number, d: number } | null}
 */
export function kstParts(iso) {
  if (typeof iso !== "string" || !iso) return null;
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  const date = new Date(ms + KST_OFFSET_MS);
  return { y: date.getUTCFullYear(), m: date.getUTCMonth() + 1, d: date.getUTCDate() };
}

const pad = (n) => String(n).padStart(2, "0");

/** @param {{ y: number, m: number }} parts @returns {string} 예: "2026년 11월" */
export const monthTitle = (parts) => `${parts.y}년 ${parts.m}월`;

/** @param {{ m: number, d: number }} parts @returns {string} 예: "11월 16일" */
export const dayTitle = (parts) => `${parts.m}월 ${parts.d}일`;

/**
 * 사진 뷰어 아래에 보일 한 줄: 날짜, 촬영일이 없으면 "보낸 날 기준"을 붙인다(촬영일을 단정하지 않는다).
 * @param {{ display_at?: string, taken_at?: string | null }} item
 * @returns {string}
 */
export function photoCaption(item) {
  const parts = kstParts(item?.display_at);
  if (!parts) return UNKNOWN_DAY;
  const day = `${parts.y}년 ${parts.m}월 ${parts.d}일`;
  return item?.taken_at == null ? `${day} · ${SENT_DAY_NOTE}` : day;
}

/**
 * 사진 목록(서버가 준 최신순)을 연·월 머리글 → 날짜 → 사진 줄(한 줄에 columns 장)로 펼친다. 같은 날 사진은 이어서 놓이고(묶음은 서버가 같은 날짜로 맞춘다),
 * 날짜가 바뀔 때만 머리글이 나온다. 읽을 수 없는 날짜는 "날짜를 알 수 없어요" 칸에 모은다(사진을 버리지 않는다).
 * @param {{ attachment_id: string, display_at?: string }[]} items
 * @param {number} [columns]
 * @returns {({ type: "month", key: string, title: string } | { type: "day", key: string, title: string } | { type: "photos", key: string, items: object[] })[]}
 */
export function buildTimelineRows(items, columns = TIMELINE_COLUMNS) {
  const rows = [];
  let monthKey = null;
  let dayKey = null;
  let bucket = null;
  const flush = () => {
    if (bucket) rows.push(bucket);
    bucket = null;
  };
  for (const item of items ?? []) {
    const parts = kstParts(item.display_at);
    const nextMonth = parts ? `${parts.y}-${pad(parts.m)}` : "unknown";
    const nextDay = parts ? `${nextMonth}-${pad(parts.d)}` : "unknown";
    if (nextMonth !== monthKey) {
      flush();
      rows.push({ type: "month", key: `m-${nextMonth}`, title: parts ? monthTitle(parts) : UNKNOWN_DAY });
      monthKey = nextMonth;
      dayKey = null;
    }
    if (nextDay !== dayKey) {
      flush();
      if (parts) rows.push({ type: "day", key: `d-${nextDay}`, title: dayTitle(parts) });
      dayKey = nextDay;
    }
    if (!bucket || bucket.items.length >= columns) {
      flush();
      bucket = { type: "photos", key: `p-${item.attachment_id}`, items: [] };
    }
    bucket.items.push(item);
  }
  flush();
  return rows;
}

/**
 * 내가 올린 사진인가(서버가 `mine` 을 준다). 내 사진만 빼기 버튼을 보인다. 서버가 최종으로 막는다(남의 사진은 404).
 * @param {{ mine?: boolean } | null | undefined} item
 * @returns {boolean}
 */
export const canExclude = (item) => item?.mine === true;

const BY_CODE = {
  not_in_timeline: "이 사진은 이미 타임라인에 없어요",
  invalid_cursor: "다음 쪽을 불러오지 못했어요. 처음부터 다시 불러와 주세요",
};

/**
 * 타임라인 조회·빼기 오류(ApiError)를 사용자 문구로. 서버 문구는 그대로 쓰지 않는다.
 * @param {{ code?: string, status?: number, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function timelineErrorMessage(error) {
  if (!error) return "";
  if (error.code === "not_in_timeline") return BY_CODE.not_in_timeline;
  if (error.code === "invalid_cursor") return BY_CODE.invalid_cursor;
  return photoCheckErrorMessage(error);
}

/**
 * 이 오류는 "이 사진은 타임라인에서 뺄 수 없다/이미 없다"(내 사진이 아니거나 지워졌거나 이미 타임라인에 없음)라 화면에서 빼도 되는가. 일시 오류(503·429·네트워크)는 남긴다.
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {boolean}
 */
export const isGoneFromTimeline = (error) => error?.status === 404 || error?.code === "not_in_timeline";

// ---------------------------------------------------------------------------------------------
// 목록 상태(번호(seq)가 다른 옛 응답은 버린다 — 화면을 떠났다 돌아오거나 다시 시도할 때 섞이지 않게)

/** @returns {{ seq: number, status: "loading" | "ready" | "error", items: object[], next: string | null, error: string, loadingMore: boolean }} */
export const initialTimelineState = () => ({ seq: 0, status: "loading", items: [], next: null, error: "", loadingMore: false });

/**
 * @param {ReturnType<typeof initialTimelineState>} state
 * @param {{ type: string, seq?: number, page?: { items?: object[], next_before?: string | null }, error?: { code?: string, status?: number, retryAfter?: number }, id?: string }} action
 * @returns {ReturnType<typeof initialTimelineState>}
 */
export function timelineReducer(state, action) {
  switch (action.type) {
    case "start":
      return { ...initialTimelineState(), seq: action.seq };
    case "firstOk":
      if (action.seq !== state.seq) return state;
      return { ...state, status: "ready", items: action.page?.items ?? [], next: action.page?.next_before ?? null, error: "" };
    case "firstFail":
      if (action.seq !== state.seq) return state;
      return { ...state, status: "error", error: timelineErrorMessage(action.error) || TIMELINE_LOAD_FAILED };
    case "moreStart":
      if (action.seq !== state.seq) return state;
      return { ...state, loadingMore: true, error: "" };
    case "moreOk": {
      if (action.seq !== state.seq) return state;
      const seen = new Set(state.items.map((it) => it.attachment_id));
      const added = (action.page?.items ?? []).filter((it) => !seen.has(it.attachment_id)); // 쪽 사이에 겹친 사진은 한 번만
      return { ...state, loadingMore: false, items: [...state.items, ...added], next: action.page?.next_before ?? null };
    }
    case "moreFail":
      if (action.seq !== state.seq) return state;
      return { ...state, loadingMore: false, error: timelineErrorMessage(action.error) || TIMELINE_LOAD_FAILED };
    case "removed": {
      // 내가 타임라인에서 뺀(또는 더 이상 타임라인에 없는) 사진: 한 번만 뺀다(원본 채팅은 건드리지 않는다)
      if (!state.items.some((it) => it.attachment_id === action.id)) return state;
      return { ...state, items: state.items.filter((it) => it.attachment_id !== action.id) };
    }
    default:
      return state;
  }
}

/**
 * 화면이 무엇을 보여 줄지. 보이는 사진을 모두 빼서 목록이 비어도 서버에 더 남은 쪽(next)이 있으면 "없어요"가 아니라 이어서 불러오거나(more) 오류와 다시 시도(more_error)를 보인다
 * — 다음 쪽 조회 실패를 빈 타임라인으로 보이지 않는다.
 * @param {ReturnType<typeof initialTimelineState>} state
 * @returns {"loading" | "error" | "list" | "more" | "more_error" | "empty"}
 */
export function timelineBodyKind(state) {
  if (state.status === "loading") return "loading";
  if (state.status === "error") return "error";
  if (state.items.length > 0) return "list";
  if (state.next != null) return state.error ? "more_error" : "more";
  return "empty";
}

/** @param {ReturnType<typeof initialTimelineState>} state 다음 쪽을 부를 수 있는가 */
export const canLoadMoreTimeline = (state) => state.status === "ready" && state.next != null && !state.loadingMore;

/**
 * "타임라인에서 빼기"를 누른 뒤의 흐름(화면과 분리해 시험한다). 내 사진이 아니거나 같은 사진이 이미 처리 중이면 서버를 부르지 않는다.
 * 같은 사진을 두 번 눌러도 요청은 한 번만 나간다(working 은 처리 중인 사진 id 집합이고 끝나면 반드시 비운다).
 * @param {{ item: { attachment_id: string, mine?: boolean } | null | undefined, working: Set<string>, exclude: (id: string) => Promise<unknown> }} args
 * @returns {Promise<{ kind: "skipped" } | { kind: "excluded" | "gone" | "failed", message: string }>} gone 은 이미 타임라인에 없음(화면에서 뺀다), failed 는 일시 오류(뷰어를 열어 둔 채 다시 시도)
 */
export async function runExclude({ item, working, exclude }) {
  const id = item?.attachment_id;
  if (!id || !canExclude(item) || working.has(id)) return { kind: "skipped" };
  working.add(id);
  try {
    await exclude(id);
    return { kind: "excluded", message: EXCLUDED_NOTICE };
  } catch (e) {
    return { kind: isGoneFromTimeline(e) ? "gone" : "failed", message: timelineErrorMessage(e) };
  } finally {
    working.delete(id);
  }
}
