/**
 * 채팅방 공유 카드(일정·정산)의 순수 로직(화면·네트워크와 무관): 카드 판별, 카드에 보일 문구, 읽어 주는 문구.
 * 카드 내용은 서버가 만든 스냅샷(`MessageOut.share = { kind, payload }`)이고 앱은 계산하지 않고 모양만 다듬는다.
 * 일정 제목·이름·금액은 어디에도 기록하지 않는다.
 */

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/** 정산 카드에서 줄을 몇 개까지 보이는지(나머지는 "외 N건"). */
export const SETTLEMENT_LINES_SHOWN = 5;
/** 일정 카드에서 같이하는 사람 이름을 몇 명까지 보이는지(나머지는 "외 N명"). */
const WITH_NAMES_SHOWN = 3;

/**
 * 공유 카드로 그릴 메시지인지: 알려진 종류(event·settlement)의 카드이고 payload 가 객체이며 지우지 않은 메시지. 모르는 종류는 일반 글 말풍선으로 둔다.
 * @param {{ share?: { kind?: string, payload?: unknown } | null, deleted?: boolean } | null | undefined} message
 * @returns {boolean}
 */
export function isShareMessage(message) {
  const share = message?.share;
  if (!share || message.deleted) return false;
  return (share.kind === "event" || share.kind === "settlement") && share.payload !== null && typeof share.payload === "object";
}

/**
 * 날짜를 "11월 12일 (목)" 으로. 비었거나 형식이 틀리면 빈 문구.
 * @param {string | null | undefined} date YYYY-MM-DD
 * @returns {string}
 */
export function formatShareDate(date) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(date ?? ""));
  if (!m) return "";
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const day = new Date(y, mo - 1, d);
  if (day.getFullYear() !== y || day.getMonth() !== mo - 1 || day.getDate() !== d) return "";
  return `${mo}월 ${d}일 (${WEEKDAYS[day.getDay()]})`;
}

/** "HH:MM"(초가 붙어도 된다)을 "오후 3:00" 으로. 틀리면 빈 문구. */
function clock(value) {
  const m = /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(String(value ?? ""));
  if (!m) return "";
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return "";
  return `${h < 12 ? "오전" : "오후"} ${h % 12 === 0 ? 12 : h % 12}:${m[2]}`;
}

/**
 * 시간 문구: 시작·끝이 있으면 "오후 3:00 ~ 오후 4:30", 시작만 있으면 "오전 9:05", 시작이 없으면 "종일"(끝만 있어도 범위를 만들지 않는다).
 * @param {string | null | undefined} start HH:MM
 * @param {string | null | undefined} end HH:MM
 * @returns {string}
 */
export function formatShareTime(start, end) {
  const from = clock(start);
  if (!from) return "종일";
  const to = clock(end);
  return to ? `${from} ~ ${to}` : from;
}

/**
 * 일정 카드에 보일 내용: 라벨(약속·할 일), 제목, 날짜·시간 한 줄, 장소, 같이하는 사람.
 * 값이 비어도 깨지지 않고(제목 "(제목 없음)", 날짜 없음 "날짜 미정") 장소·같이하는 사람은 없으면 빈 문구다.
 * @param {{ title?: string | null, date?: string | null, start_time?: string | null, end_time?: string | null, place?: string | null, kind?: number, with_names?: (string | null)[] | null } | null | undefined} payload
 * @returns {{ badge: "약속" | "할 일", title: string, when: string, place: string, withText: string }}
 */
export function eventCardView(payload) {
  const p = payload ?? {};
  const date = formatShareDate(p.date);
  const time = date || p.start_time ? formatShareTime(p.start_time, p.end_time) : "";
  const names = (Array.isArray(p.with_names) ? p.with_names : []).map((n) => String(n ?? "").trim()).filter(Boolean);
  const shown = names.slice(0, WITH_NAMES_SHOWN).join(", ");
  return {
    badge: p.kind === 2 ? "할 일" : "약속",
    title: String(p.title ?? "").trim() || "(제목 없음)",
    when: [date || "날짜 미정", time].filter(Boolean).join(" · "),
    place: String(p.place ?? "").trim(),
    withText: names.length ? `함께 ${shown}${names.length > WITH_NAMES_SHOWN ? ` 외 ${names.length - WITH_NAMES_SHOWN}명` : ""}` : "",
  };
}

/**
 * 금액을 "12,000원" 으로(음수는 절댓값, 방향은 문구가 말한다). 숫자가 아니면 빈 문구.
 * @param {number | null | undefined} amount
 * @returns {string}
 */
export function formatShareMoney(amount) {
  if (typeof amount !== "number" || !Number.isFinite(amount)) return "";
  return `${Math.abs(Math.round(amount)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")}원`;
}

/**
 * 정산 월을 "2026년 11월" 로. 형식이 틀리면 빈 문구.
 * @param {string | null | undefined} month YYYY-MM
 * @returns {string}
 */
export function formatShareMonth(month) {
  const m = /^(\d{4})-(\d{2})$/.exec(String(month ?? ""));
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return "";
  return `${m[1]}년 ${Number(m[2])}월`;
}

/**
 * 정산 카드에 보일 내용: 월, 내 남은 잔액 한 줄(받을 돈·보낼 돈·없음), 송금 줄(최대 SETTLEMENT_LINES_SHOWN 개)과 나머지 개수.
 * 금액은 서버가 만든 값 그대로 보이고 앱이 다시 계산하지 않는다. 이름이 없는 줄은 "상대", 금액이 숫자가 아닌 줄은 건너뛴다.
 * @param {{ month?: string, remaining?: number, lines?: ({ direction?: string, name?: string, amount?: number } | null)[] } | null | undefined} payload
 * @returns {{ month: string, summary: { tone: "receive" | "send" | "even", text: string }, lines: { key: string, text: string }[], moreCount: number }}
 */
export function settlementCardView(payload) {
  const p = payload ?? {};
  const rem = typeof p.remaining === "number" && Number.isFinite(p.remaining) ? p.remaining : 0;
  const summary = rem > 0 ? { tone: "receive", text: `받을 돈 ${formatShareMoney(rem)}` } : rem < 0 ? { tone: "send", text: `보낼 돈 ${formatShareMoney(rem)}` } : { tone: "even", text: "정산할 돈이 없어요" };
  const all = [];
  (Array.isArray(p.lines) ? p.lines : []).forEach((line, i) => {
    const money = formatShareMoney(line?.amount);
    if (!money) return;
    const name = String(line.name ?? "").trim() || "상대";
    all.push({ key: String(i), text: `${name}님에게 ${money} ${line.direction === "receive" ? "받아요" : "보내요"}` });
  });
  return { month: formatShareMonth(p.month), summary, lines: all.slice(0, SETTLEMENT_LINES_SHOWN), moreCount: Math.max(0, all.length - SETTLEMENT_LINES_SHOWN) };
}

/**
 * 스크린리더가 읽어 줄 카드 문구(일정: 라벨·제목·날짜시간·장소·함께, 정산: 월·잔액·송금 줄).
 * @param {{ kind: "event" | "settlement", payload: object }} share
 * @returns {string}
 */
export function shareA11yLabel(share) {
  if (share?.kind === "settlement") {
    const v = settlementCardView(share.payload);
    return ["정산 공유 카드", v.month, v.summary.text, ...v.lines.map((l) => l.text), v.moreCount ? `외 ${v.moreCount}건` : ""].filter(Boolean).join(", ");
  }
  const v = eventCardView(share?.payload);
  return ["일정 공유 카드", v.badge, v.title, v.when, v.place ? `장소 ${v.place}` : "", v.withText].filter(Boolean).join(", ");
}
