/** @param {number} n 정수 원 @returns {string} 예: 12,300원 */
export const won = (n) => `${Number(n).toLocaleString("ko-KR")}원`;

/** @returns {string} 이번 달 YYYY-MM (기기 시간 기준) */
export function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** @param {string} month YYYY-MM @param {number} delta 더할 달 수(음수 가능) @returns {string} */
export function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * 금액 입력칸에 보여 줄 글자: 숫자만 남기고 세 자리마다 쉼표를 넣는다(앞의 0은 뺀다).
 * @param {string | number | null | undefined} text 입력 중인 글자(쉼표가 이미 있어도 된다)
 * @returns {string} 예: "1234567" → "1,234,567", 숫자가 하나도 없으면 ""
 */
export function formatMoneyInput(text) {
  const digits = String(text ?? "")
    .replace(/\D/g, "")
    .replace(/^0+(?=\d)/, "");
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** @param {string | number | null | undefined} text 금액 입력 글자 @returns {string} 쉼표·공백을 뺀 글자 */
export const stripMoney = (text) => String(text ?? "").replace(/[,\s]/g, "");

/** @param {string} text 사용자가 입력한 금액(쉼표 가능) @returns {number} 정수 원, 숫자가 아니면 NaN */
export const parseWon = (text) => {
  const plain = stripMoney(text);
  return /^\d+$/.test(plain) ? parseInt(plain, 10) : NaN;
};

/** 지출 내역을 한 번에 보여 주는 개수(더보기를 누를 때마다 이만큼 늘어난다) */
export const PAGE_SIZE = 5;

/**
 * "더보기" 버튼에 쓸 남은 개수.
 * @param {number} total 전체 개수
 * @param {number} shown 지금 보이는 개수
 * @returns {number} 아직 안 보이는 개수(0 이상)
 */
export const remaining = (total, shown) => Math.max(0, total - shown);

/** 정산 대상 태그 이름. custom 은 정산하는 사람이 나눌 사람을 직접 고른 경우다. */
export const TAG_LABEL = { parents: "부모님 대상", children: "자녀 대상", all: "가족 전체", custom: "직접 고름" };
