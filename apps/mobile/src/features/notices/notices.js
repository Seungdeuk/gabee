/**
 * 공지사항 화면의 글자와 계산(화면과 따로 시험할 수 있게 순수 함수로 둔다).
 */

export const CATEGORY_LABEL = { update: "업데이트", info: "안내", maintenance: "점검" };

export const EMPTY_TEXT = "아직 공지가 없어요.";
export const HELP_TEXT = "궁금한 점은 더보기 › 고객센터에서 문의해 주세요.";

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/** 한 쪽에 보이는 공지 수. 이보다 많아지면 쪽으로 나눈다. */
export const PAGE_SIZE = 10;
/** 쪽 번호를 한 번에 보이는 개수(< 1 | 2 | 3 | 4 | 5 >). */
export const PAGE_WINDOW = 5;

/**
 * 전체 쪽 수(공지가 없거나 한 쪽이면 1).
 * @param {number | null | undefined} total 공지 수
 * @returns {number}
 */
export function pageCount(total) {
  return Math.max(1, Math.ceil((Number(total) || 0) / PAGE_SIZE));
}

/**
 * 그 쪽(0부터)에 보일 공지. 서버가 준 최근순 그대로 PAGE_SIZE 개씩 자른다.
 * @param {object[] | null | undefined} rows
 * @param {number} page
 * @returns {object[]}
 */
export function pageSlice(rows, page) {
  const list = Array.isArray(rows) ? rows : [];
  return list.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
}

/**
 * 쪽이 범위를 벗어나지 않게 한다(새로고침으로 목록이 줄어도 빈 쪽이 보이지 않게).
 * @param {number} page
 * @param {number | null | undefined} total 공지 수
 * @returns {number}
 */
export function clampPage(page, total) {
  const last = pageCount(total) - 1;
  return Number.isFinite(page) ? Math.min(Math.max(0, Math.floor(page)), last) : 0;
}

/**
 * 쪽 번호 줄에 보일 쪽들(0부터). PAGE_WINDOW 개씩 묶어 1~5, 6~10, … 처럼 보이고 마지막 묶음은 남은 만큼이다.
 * @param {number} page 지금 쪽
 * @param {number} pages 전체 쪽 수
 * @returns {number[]}
 */
export function pageWindow(page, pages) {
  const start = Math.floor(page / PAGE_WINDOW) * PAGE_WINDOW;
  const end = Math.min(start + PAGE_WINDOW, pages);
  return Array.from({ length: Math.max(0, end - start) }, (_, i) => start + i);
}

/**
 * 아직 열어 보지 않은 공지 수.
 * @param {object[] | null} rows
 * @param {Set<string>} readIds
 */
export function unreadCount(rows, readIds) {
  return (Array.isArray(rows) ? rows : []).filter((n) => !readIds.has(n.id)).length;
}

/**
 * 한국 시간 날짜 "2026.11.04". 잘못된 값이면 빈 글자.
 * @param {string | null | undefined} iso
 */
export function noticeDate(iso) {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const kst = new Date(at.getTime() + KST_OFFSET_MS);
  const pad = (n) => String(n).padStart(2, "0");
  return `${kst.getUTCFullYear()}.${pad(kst.getUTCMonth() + 1)}.${pad(kst.getUTCDate())}`;
}

/**
 * 목록 카드에 보일 본문 앞부분(첫 줄, 60자까지).
 * @param {string} body
 */
export function preview(body) {
  const line = String(body ?? "").trim().split("\n").find((l) => l.trim()) ?? "";
  return line.length > 60 ? `${line.slice(0, 60)}…` : line;
}

/**
 * 목록을 못 받았을 때 보여 줄 문구.
 * @param {{ status?: number, code?: string } | null} error
 */
export function noticesErrorMessage(error) {
  if (!error) return "";
  if (error.code === "api_not_configured") return "서버 주소가 설정되지 않았어요";
  if (error.status === 401) return "로그인이 필요해요. 다시 로그인해 주세요";
  if (error.status === 503) return "공지사항을 잠시 볼 수 없어요. 조금 뒤에 다시 시도해 주세요";
  return "공지사항을 불러오지 못했어요. 잠시 뒤에 다시 시도해 주세요";
}
