/** @param {number} n 정수 원 @returns {string} 예: 12,300원 */
export const won = (n) => `${Number(n).toLocaleString("ko-KR")}원`;

/**
 * @param {Date} [now] 기준 시각(시험용, 기본은 지금)
 * @returns {string} 이번 달 YYYY-MM (기기 시간 기준)
 */
export function currentMonth(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** @param {string} month YYYY-MM @returns {number} 그 달의 일 수(윤년 반영) */
export function daysInMonth(month) {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m, 0).getDate();
}

/**
 * 지출 입력 폼의 처음 날짜(일): 이번 달을 보고 있으면 오늘, 다른 달이면 1일.
 * @param {string} month 보고 있는 달 YYYY-MM @param {Date} [now] 시험용 기준 시각
 * @returns {number}
 */
export const defaultDay = (month, now = new Date()) => (month === currentMonth(now) ? now.getDate() : 1);

/** @param {string} month YYYY-MM @param {number | string} day 입력한 일 @returns {number} 1~그 달 말일로 맞춘 정수(숫자가 아니면 1) */
export function clampDay(month, day) {
  const n = Math.trunc(Number(day));
  if (!Number.isFinite(n)) return 1;
  return Math.min(Math.max(n, 1), daysInMonth(month));
}

/** @param {string} month YYYY-MM @param {number | string} day @returns {string} 서버에 보낼 YYYY-MM-DD(없는 날은 말일로 맞춘다) */
export const expenseDate = (month, day) => `${month}-${String(clampDay(month, day)).padStart(2, "0")}`;

/**
 * 빠른 날짜 선택: "오늘"과 "어제". 보고 있는 달 안에 있을 때만 준다(내역이 그 달만 보이기 때문).
 * @param {string} month YYYY-MM @param {Date} [now] 시험용 기준 시각
 * @returns {{ label: string, day: number }[]}
 */
export function quickDays(month, now = new Date()) {
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  return [
    { label: "오늘", date: now },
    { label: "어제", date: yesterday },
  ]
    .filter((q) => currentMonth(q.date) === month)
    .map((q) => ({ label: q.label, day: q.date.getDate() }));
}

/** @param {string} month YYYY-MM @returns {{ value: number, label: string }[]} 일 휠 선택지(1일~말일) */
export const dayOptions = (month) => Array.from({ length: daysInMonth(month) }, (_, i) => ({ value: i + 1, label: `${i + 1}일` }));

/** @param {string} month YYYY-MM @param {string} text 직접 입력한 글자 @returns {number | null} 1~말일이면 그 값, 아니면 null */
export function parseDayInput(month, text) {
  const digits = String(text ?? "").replace(/[^0-9]/g, "");
  if (!digits) return null;
  const n = Number(digits);
  return n >= 1 && n <= daysInMonth(month) ? n : null;
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

/**
 * 앱에서 고칠 수 있는 지출인가: 내가 낸 지출이고 정산하기를 마치기 전이어야 한다(서버 규칙과 같다. 송금 완료가 있는 달의 잠금은
 * 서버가 알려 준다).
 * @param {{ paid_by: string, settled?: boolean }} expense @param {string | null | undefined} myId 로그인한 나
 * @returns {boolean}
 */
export const canEditExpense = (expense, myId) => Boolean(myId) && expense.paid_by === myId && !expense.settled;

/**
 * 지금 값과 다른 것만 담은 수정 요청 바디. 바뀐 것이 없으면 빈 객체.
 * @param {{ title: string, amount: number, date: string }} old 서버에서 받은 지출
 * @param {{ title: string, amount: number, date: string }} next 폼에서 정한 값(제목은 다듬은 값)
 * @returns {{ title?: string, amount?: number, date?: string }}
 */
export function expensePatch(old, next) {
  const patch = {};
  for (const key of ["title", "amount", "date"]) if (next[key] !== old[key]) patch[key] = next[key];
  return patch;
}
