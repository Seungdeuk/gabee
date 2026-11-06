/**
 * 공지사항 화면의 글자와 계산(화면과 따로 시험할 수 있게 순수 함수로 둔다).
 */

export const CATEGORY_LABEL = { update: "업데이트", info: "안내", maintenance: "점검" };

export const CHIPS = [
  { key: "all", label: "전체" },
  { key: "update", label: "업데이트" },
  { key: "info", label: "안내" },
  { key: "maintenance", label: "점검" },
];

export const EMPTY_TEXT = "이 종류의 공지는 아직 없어요.";
export const HELP_TEXT = "궁금한 점은 더보기 › 고객센터에서 문의해 주세요.";

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 고른 칩의 공지만 남긴다. 모르는 칩이면 전체.
 * @param {object[] | null} rows
 * @param {string} chip
 */
export function filterNotices(rows, chip) {
  const list = Array.isArray(rows) ? rows : [];
  return chip in CATEGORY_LABEL ? list.filter((n) => n.category === chip) : list;
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
