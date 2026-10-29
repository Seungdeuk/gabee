// 게시판 목록 화면(지난 공지 포함)의 순수 함수. 화면·네트워크와 분리해 시험한다. 공지 글자는 어디에도 기록하지 않는다.
import { formatTime, parseTime } from "./chatUtils";
import { focusRoute } from "./searchUtils";

/** 목록 위 선택 칩. all: 지난 공지까지 모두, current: 지금 채팅방 위 공지 바에 있는 것만. */
export const BOARD_FILTERS = [
  { key: "all", label: "전체" },
  { key: "current", label: "현재 공지" },
];

/** 목록에서 한 줄로 보이는 본문 길이. 넘으면 말줄임표를 붙이고 전체는 상세에서 본다. */
export const BOARD_PREVIEW_MAX = 90;

export const DELETED_NOTICE = "게시판에서 삭제했어요";
export const ALREADY_GONE_NOTICE = "이미 삭제된 글이에요";

/**
 * 서버 항목을 화면이 쓰는 모양으로(없는 값은 안전한 기본값).
 * @param {object} raw 서버 BoardItem
 * @returns {{ id: string, message_id: number, text: string, user_id: string, user_name: string, message_created_at: string, posted_by: string, posted_by_name: string, posted_at: string, is_current: boolean, message_deleted: boolean }}
 */
export function normalizeBoardItem(raw) {
  return {
    id: String(raw?.id ?? ""),
    message_id: Number(raw?.message_id),
    text: String(raw?.text ?? ""),
    user_id: String(raw?.user_id ?? ""),
    user_name: String(raw?.user_name ?? ""),
    message_created_at: String(raw?.message_created_at ?? ""),
    posted_by: String(raw?.posted_by ?? ""),
    posted_by_name: String(raw?.posted_by_name ?? ""),
    posted_at: String(raw?.posted_at ?? ""),
    is_current: Boolean(raw?.is_current),
    message_deleted: Boolean(raw?.message_deleted),
  };
}

/**
 * 받아 둔 목록 뒤에 다음 쪽을 붙인다. 같은 id 는 새 값으로 바꾸고(다시 올려 갱신된 글) 순서는 올린 시각 최신순을 지킨다.
 * @param {object[]} current 지금 목록
 * @param {object[]} incoming 서버에서 온 항목들
 * @returns {object[]}
 */
export function mergeBoard(current, incoming) {
  const byId = new Map();
  for (const it of [...(current ?? []), ...(incoming ?? []).map(normalizeBoardItem)]) byId.set(it.id, it);
  return [...byId.values()].sort((a, b) => parseTime(b.posted_at) - parseTime(a.posted_at) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
}

/**
 * 칩에 맞게 거른다(받아 둔 목록 안에서).
 * @param {object[]} items
 * @param {"all" | "current"} filter
 * @returns {object[]}
 */
export const filterBoard = (items, filter) => (filter === "current" ? (items ?? []).filter((it) => it.is_current) : items ?? []);

/**
 * 목록 카드의 본문 앞부분(줄바꿈은 공백으로).
 * @param {{ text?: string }} item
 * @returns {string}
 */
export function boardPreview(item) {
  const line = String(item?.text ?? "").replace(/\s+/g, " ").trim();
  return line.length > BOARD_PREVIEW_MAX ? `${line.slice(0, BOARD_PREVIEW_MAX).trimEnd()}…` : line;
}

/**
 * 올린 사람·시각 보조 줄: "엄마 올림 · 10월 24일 오후 3:20".
 * @param {{ posted_by?: string, posted_by_name?: string, posted_at?: string }} item
 * @param {(userId: string) => string | undefined} [nameOf] 사용자 id → 표시 이름(별명). 모르면 서버가 준 이름
 * @returns {string}
 */
export function boardMeta(item, nameOf) {
  const who = nameOf?.(item?.posted_by) || item?.posted_by_name || "가족";
  const d = parseTime(item?.posted_at);
  if (Number.isNaN(d.getTime())) return `${who} 올림`;
  return `${who} 올림 · ${d.getMonth() + 1}월 ${d.getDate()}일 ${formatTime(item.posted_at)}`;
}

/**
 * 메시지를 쓴 사람 줄: "지민 님이 쓴 글". 올린 사람과 같으면 따로 보여 줄 필요가 없어 null.
 * @param {object} item
 * @param {(userId: string) => string | undefined} [nameOf]
 * @returns {string | null}
 */
export function boardAuthor(item, nameOf) {
  if (!item?.user_id || item.user_id === item.posted_by) return null;
  return `${nameOf?.(item.user_id) || item.user_name || "가족"} 님이 쓴 글`;
}

/**
 * 카드 한 개의 접근성 라벨.
 * @param {object} item
 * @param {(userId: string) => string | undefined} [nameOf]
 * @returns {string}
 */
export function boardA11y(item, nameOf) {
  const state = item?.is_current ? "현재 공지, " : "지난 공지, ";
  const gone = item?.message_deleted ? " 원본 메시지는 삭제됐어요." : "";
  return `${state}${boardPreview(item)}. ${boardMeta(item, nameOf)}.${gone} 누르면 전체 내용을 봐요`;
}

/** 칩별 빈 목록 문구. */
export const boardEmptyText = (filter) => (filter === "current" ? "지금 올라 있는 공지가 없어요" : "아직 게시판에 올린 공지가 없어요");

/**
 * 오류 문구.
 * @param {{ status?: number } | null | undefined} error
 * @returns {string}
 */
export function boardErrorMessage(error) {
  if (error?.status === 404) return "채팅방을 찾을 수 없어요";
  if (error?.status === 429) return "잠시 후 다시 시도해 주세요";
  if (error?.status === 0) return "서버에 연결하지 못했어요";
  return "게시판을 불러오지 못했어요";
}

/**
 * 삭제 실패 문구. 404 는 이미 지워진 글이라 목록에서도 빼는 쪽으로 처리한다(boardDeleteOutcome).
 * @param {{ status?: number } | null | undefined} error
 * @returns {string}
 */
export function boardDeleteErrorMessage(error) {
  if (error?.status === 429) return "잠시 후 다시 시도해 주세요";
  if (error?.status === 0) return "서버에 연결하지 못했어요";
  return "삭제하지 못했어요";
}

/**
 * 삭제 요청 결과를 화면 처리로: 성공이거나 이미 없는 글(404)이면 목록에서 빼고(remove), 그 밖에는 목록을 그대로 둔다(keep).
 * @param {{ status?: number } | null} error 성공이면 null
 * @returns {{ effect: "remove" | "keep", notice: string }}
 */
export function boardDeleteOutcome(error) {
  if (!error) return { effect: "remove", notice: DELETED_NOTICE };
  if (error.status === 404) return { effect: "remove", notice: ALREADY_GONE_NOTICE };
  return { effect: "keep", notice: boardDeleteErrorMessage(error) };
}

/**
 * "채팅에서 보기"를 눌러 갈 수 있는지: 원본 메시지가 남아 있을 때만.
 * @param {{ message_deleted?: boolean }} item
 * @returns {boolean}
 */
export const canOpenOriginal = (item) => Boolean(item) && !item.message_deleted;

/**
 * 원본 메시지 위치로 가는 채팅방 경로(검색 결과로 이동할 때와 같은 방식).
 * @param {{ roomId?: string | null, peerId?: string | null, messageId: number }} args roomId 가 없으면 가족 전체방
 * @returns {{ pathname: string, params: Record<string, string> }}
 */
export const originalRoute = ({ roomId, peerId, messageId }) =>
  focusRoute({ id: messageId, room_kind: roomId ? "direct" : "family", room_id: roomId ?? undefined, peer_user_id: peerId ?? undefined });

/**
 * 처음 상태. seq 는 "지금 유효한 요청 번호"다 — 이 번호가 아닌 응답은 버려진다.
 * @returns {{ seq: number, items: object[], next: string | null, status: "loading" | "ready" | "error", error: string, loadingMore: boolean }}
 */
export const initialBoardState = () => ({ seq: 0, items: [], next: null, status: "loading", error: "", loadingMore: false });

/**
 * 상태 전이(모음 화면과 같은 규칙). start 는 방이 바뀌었거나 다시 시도할 때, firstOk/firstFail 은 첫 쪽 결과, moreStart/moreOk/moreFail 은 다음 쪽,
 * removed 는 삭제한 글을 목록에서 뺀다(요청 번호와 무관).
 * @param {ReturnType<typeof initialBoardState>} state
 * @param {{ type: string, seq?: number, id?: string, page?: { items?: object[], next_before?: string | null }, error?: { status?: number } }} action
 * @returns {ReturnType<typeof initialBoardState>}
 */
export function boardReducer(state, action) {
  if (action.type === "start") return { ...initialBoardState(), seq: action.seq };
  if (action.type === "removed") return { ...state, items: state.items.filter((it) => it.id !== action.id) };
  if (action.seq !== state.seq) return state; // 옛 요청의 응답
  switch (action.type) {
    case "firstOk":
      return { ...state, items: mergeBoard([], action.page.items), next: action.page.next_before ?? null, status: "ready", error: "", loadingMore: false };
    case "firstFail":
      return { ...state, items: [], next: null, status: "error", error: boardErrorMessage(action.error), loadingMore: false };
    case "moreStart":
      return { ...state, loadingMore: true, error: "" };
    case "moreOk":
      return { ...state, items: mergeBoard(state.items, action.page.items), next: action.page.next_before ?? null, loadingMore: false };
    case "moreFail":
      return { ...state, loadingMore: false, error: boardErrorMessage(action.error) };
    default:
      return state;
  }
}

/**
 * 다음 쪽을 요청해도 되는지: 첫 쪽을 받았고, 이어 받을 커서가 있고, 받는 중이 아닐 때.
 * @param {ReturnType<typeof initialBoardState>} state
 * @returns {boolean}
 */
export const canLoadMoreBoard = (state) => state.status === "ready" && state.next != null && !state.loadingMore;
