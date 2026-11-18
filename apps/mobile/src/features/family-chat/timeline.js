// 가족 타임라인의 순수 함수·문구·상태 전이(화면·네트워크와 분리해 시험한다). 사진 내용·대화 글자는 어디에도 기록하지 않는다.
// 어떤 사진이 타임라인에 나오는지는 서버가 정한다(일반 사진으로 확인된 가족 전체방 사진만). 앱은 받은 목록을 날짜로 묶어 보일 뿐 숨기거나 더하지 않는다.

import { albumCells } from "./album";
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

/** 1장짜리 카드의 세로/가로 비율(4:3). 서버가 사진의 가로·세로를 주지 않아 고정 비율로 자른다. */
export const SINGLE_CARD_RATIO = 0.75;

/** 다음 쪽을 불러오는 요청이 이 시간(ms) 안에 끝나지 않으면, 쪽 경계 때문에 보류하던 묶음을 먼저 보인다(무기한 숨기지 않는다). */
export const BUNDLE_HOLD_MS = 8000;

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

/** 사진이 속한 한국 시간 날짜 키(읽을 수 없으면 "unknown"). */
function dayKeyOf(item) {
  const parts = kstParts(item?.display_at);
  return parts ? `${parts.y}-${pad(parts.m)}-${pad(parts.d)}` : "unknown";
}

/** 묶음 안 순서: 올린 순서(메시지 번호 오름차순, 채팅 앨범과 같다). 번호가 없거나 같으면 받은 순서를 지킨다. */
function byUploadOrder(a, b) {
  const ma = Number(a.message_id);
  const mb = Number(b.message_id);
  return Number.isFinite(ma) && Number.isFinite(mb) && ma !== mb ? ma - mb : 0;
}

/**
 * 사진 목록(서버가 준 최신순)을 연·월 머리글 → 날짜 → 묶음 카드로 펼친다. 같은 날짜 칸 안에서 같은 `batch_id` 사진은 하나의 카드로 모으고(중간에 다른 사진이 끼어 있어도),
 * `batch_id` 가 없는 사진은 1장짜리 카드다. 카드 안 순서는 올린 순서이고, 카드 순서는 처음 나온 순서(서버의 최신순)다. 같은 `batch_id` 라도 날짜가 다르면 날짜마다 따로 카드가 된다.
 * 목록에 있는 사진만 그린다(더하거나 숨기지 않는다). 읽을 수 없는 날짜는 "날짜를 알 수 없어요" 칸에 모은다(사진을 버리지 않는다).
 * 카드 key 는 묶음이 쪽을 넘어 자라도 바뀌지 않는다(`b-날짜-batch_id`, 1장은 `p-사진id`).
 * @param {{ attachment_id: string, message_id?: number, batch_id?: string | null, display_at?: string }[]} items
 * @returns {({ type: "month", key: string, title: string } | { type: "day", key: string, title: string } | { type: "bundle", key: string, photos: object[] })[]}
 */
export function buildTimelineRows(items) {
  const rows = [];
  let monthKey = null;
  let dayKey = null;
  let bundles = null; // 지금 날짜 칸의 카드들(처음 나온 순서)
  const flush = () => {
    if (!bundles) return;
    for (const bundle of bundles.values()) {
      bundle.photos.sort(byUploadOrder);
      rows.push(bundle);
    }
    bundles = null;
  };
  for (const item of items ?? []) {
    const parts = kstParts(item.display_at);
    const nextMonth = parts ? `${parts.y}-${pad(parts.m)}` : "unknown";
    const nextDay = dayKeyOf(item);
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
      bundles = new Map();
    }
    const key = item.batch_id ? `b-${nextDay}-${item.batch_id}` : `p-${item.attachment_id}`;
    const existing = bundles.get(key);
    if (existing) existing.photos.push(item);
    else bundles.set(key, { type: "bundle", key, photos: [item] });
  }
  flush();
  return rows;
}

/**
 * 묶음 카드의 칸 배치(채팅 앨범과 같은 규칙, 1장만 큰 카드). 1장은 한 칸(가로 전체, 4:3), 2장은 나란히, 3장은 위 한 장 + 아래 두 장, 4장 이상은 2×2 에 마지막 칸 "+N".
 * @param {number} count 카드의 사진 수
 * @param {number} width 카드 가로
 * @returns {{ cells: { width: number, height: number }[], more: number }}
 */
export function bundleCells(count, width) {
  const n = Math.max(0, Math.floor(count) || 0);
  if (n === 1) return { cells: [{ width, height: Math.round(width * SINGLE_CARD_RATIO) }], more: 0 };
  return albumCells(n, width);
}

/**
 * 쪽 경계에서 같은 묶음이 갈라져 보이지 않게, 더 불러올 쪽이 있으면 목록 **끝에 걸친 묶음**(마지막 사진과 같은 날짜·같은 batch_id)을 잠시 보류한다. 다음 쪽이 오면 묶음이 완성되어 보인다.
 * 아래 경우에는 보류하지 않고 가진 사진을 모두 보인다: 더 불러올 쪽이 없다 / 다음 쪽 불러오기가 실패했다(failed) / 불러오는 요청이 너무 오래 걸렸다(expired).
 * 묶음이 없는 사진은 갈라질 일이 없어 보류하지 않는다.
 * @param {{ attachment_id: string, batch_id?: string | null, display_at?: string }[]} items
 * @param {{ hasMore: boolean, failed?: boolean, expired?: boolean }} state
 * @returns {{ shown: object[], held: object[] }} shown 은 그릴 사진(원래 순서), held 는 보류한 사진
 */
export function splitHeldBack(items, { hasMore, failed = false, expired = false } = {}) {
  const list = items ?? [];
  if (!hasMore || failed || expired || list.length === 0) return { shown: list, held: [] };
  const last = list[list.length - 1];
  if (!last.batch_id) return { shown: list, held: [] };
  const day = dayKeyOf(last);
  const isHeld = (it) => it.batch_id === last.batch_id && dayKeyOf(it) === day;
  return { shown: list.filter((it) => !isHeld(it)), held: list.filter(isHeld) };
}

/**
 * 뷰어에 넘길 사진들: 카드를 누른 순간의 사진들을 그대로 복사한다(뷰어를 보는 동안 다음 쪽이 와서 카드가 자라도 보던 사진 번호가 밀리지 않는다).
 * url 은 서버가 준 원본 경로 규칙(`/family-chat/photos/{id}`)이다.
 * @param {{ photos: object[] } | null | undefined} bundle buildTimelineRows 의 카드
 * @returns {{ id: string, url: string, item: object }[]}
 */
export function viewerPhotos(bundle) {
  return (bundle?.photos ?? []).map((item) => ({ id: item.attachment_id, url: `/family-chat/photos/${encodeURIComponent(item.attachment_id)}`, item }));
}

/**
 * 뷰어 안에서 사진 한 장을 빼거나(타임라인에서 제외) 이미 없는 사진이 된 뒤의 뷰어 상태. 남은 사진이 있으면 그대로 열어 두고(지금 보던 번호에 다음 사진이 온다, 마지막이었으면 새 마지막), 없으면 닫는다(null).
 * @param {{ photos: { id: string }[], index: number } | null} viewer
 * @param {string} removedId 뺀 사진 id
 * @param {number} [currentIndex] 뷰어가 지금 보고 있던 번호(없으면 viewer.index)
 * @returns {{ photos: { id: string }[], index: number } | null}
 */
export function viewerAfterRemoval(viewer, removedId, currentIndex) {
  if (!viewer) return null;
  const photos = viewer.photos.filter((p) => p.id !== removedId);
  if (photos.length === 0) return null;
  const at = Number.isInteger(currentIndex) ? currentIndex : viewer.index;
  return { photos, index: Math.max(0, Math.min(at, photos.length - 1)) };
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
