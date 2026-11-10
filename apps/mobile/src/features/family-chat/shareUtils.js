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

/**
 * "HH:MM"(초가 붙어도 된다)을 "오후 3:00" 으로. 틀리면 빈 문구.
 * @param {string | null | undefined} value
 * @returns {string}
 */
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

/** 보낸 사람 이름이 비었을 때 문장에 쓰는 이름. */
const SENDER_FALLBACK = "보낸 사람";

/**
 * 문장에 쓸 보낸 사람 이름: 이름이 있으면 "하늘님", 없으면 "보낸 사람"(이름 뒤에 "님"을 붙이지 않는다).
 * @param {string | null | undefined} senderName
 * @returns {string}
 */
function senderLabel(senderName) {
  const name = String(senderName ?? "").trim();
  return name ? `${name}님` : SENDER_FALLBACK;
}

/**
 * 정산 카드에 보일 내용: 월, 보낸 사람 기준 남은 잔액 한 줄(받을 돈·보낼 돈·없음), 송금 줄(최대 SETTLEMENT_LINES_SHOWN 개)과 나머지 개수.
 * 서버 payload 는 카드를 보낸 사람 기준이다(remaining +/− 와 lines 의 send·receive 모두. 1:1 방에서는 그 상대와의 줄과 그 합계).
 * 내 카드(mine, 기본)는 "받을 돈 12,000원"·"수진님에게 12,000원 받아요" 처럼 주어 없이, 남의 카드는 보는 사람이 자기 돈으로 오해하지 않도록 보낸 사람 이름을 주어로 쓴다
 * ("하늘님이 받을 돈 12,000원"·"수진님이 하늘님에게 12,000원 보내요"). 이름이 비면 "보낸 사람". 0원이면 내 카드는 "정산할 돈이 없어요", 남의 카드는 "하늘님은 정산할 돈이 없어요".
 * 금액은 서버가 만든 값 그대로 보이고 앱이 다시 계산하지 않는다. 이름이 없는 상대 줄은 "상대", 금액이 숫자가 아니거나 방향(send·receive)을 모르는 줄은 건너뛴다.
 * @param {{ month?: string, remaining?: number, lines?: ({ direction?: string, name?: string, amount?: number } | null)[] } | null | undefined} payload
 * @param {{ mine?: boolean, senderName?: string | null }} [options] mine 기본 true(내 카드), senderName 은 남의 카드의 보낸 사람 이름
 * @returns {{ month: string, summary: { tone: "receive" | "send" | "even", text: string }, lines: { key: string, text: string }[], moreCount: number }}
 */
export function settlementCardView(payload, { mine = true, senderName = "" } = {}) {
  const p = payload ?? {};
  const who = senderLabel(senderName);
  const subject = mine ? "" : `${who}이 `;
  const rem = typeof p.remaining === "number" && Number.isFinite(p.remaining) ? p.remaining : 0;
  const summary = rem > 0 ? { tone: "receive", text: `${subject}받을 돈 ${formatShareMoney(rem)}` } : rem < 0 ? { tone: "send", text: `${subject}보낼 돈 ${formatShareMoney(rem)}` } : { tone: "even", text: mine ? "정산할 돈이 없어요" : `${who}은 정산할 돈이 없어요` };
  const all = [];
  (Array.isArray(p.lines) ? p.lines : []).forEach((line, i) => {
    const money = formatShareMoney(line?.amount);
    if (!money || (line.direction !== "send" && line.direction !== "receive")) return; // 돈의 방향을 모르면 건너뛴다(방향을 잘못 말하지 않게)
    const other = String(line.name ?? "").trim() || "상대";
    let text;
    if (mine) text = `${other}님에게 ${money} ${line.direction === "receive" ? "받아요" : "보내요"}`;
    else text = line.direction === "send" ? `${who}이 ${other}님에게 ${money} 보내요` : `${other}님이 ${who}에게 ${money} 보내요`;
    all.push({ key: String(i), text });
  });
  return { month: formatShareMonth(p.month), summary, lines: all.slice(0, SETTLEMENT_LINES_SHOWN), moreCount: Math.max(0, all.length - SETTLEMENT_LINES_SHOWN) };
}

/**
 * 카드 안 글자색의 이름(theme 의 colors 키). 정산의 받을 돈·보낼 돈은 색이 아니라 글자("받을 돈"·"보낼 돈")로 가리므로 어느 말풍선에서든 본문색이다
 * (복숭아색 내 말풍선 위의 초록·빨강은 대비가 2.7~3.5:1 이고 남의 카드는 주어가 있는 문장으로 구분한다). 보조 글자(sub)만 남의 카드(흰 바탕)에서 textSub, 내 말풍선에서는 대비를 위해 본문색이다.
 * @param {{ mine: boolean, tone: "receive" | "send" | "even" | "sub" }} args tone: 정산 요약 줄의 종류, 또는 보조 글자(sub)
 * @returns {"text" | "textSub"}
 */
export function shareTextTone({ mine, tone }) {
  return !mine && tone === "sub" ? "textSub" : "text";
}

/**
 * 스크린리더가 읽어 줄 카드 문구(일정: 라벨·제목·날짜시간·장소·함께, 정산: 월·잔액·송금 줄). 남의 정산 카드는 "하늘님이 공유"처럼 보낸 사람 이름(없으면 "보낸 사람")을 넣고 주어가 있는 문장으로 읽는다.
 * @param {{ kind: "event" | "settlement", payload: object }} share
 * @param {{ mine?: boolean, senderName?: string | null }} [options] mine 기본 true(내 카드)
 * @returns {string}
 */
export function shareA11yLabel(share, { mine = true, senderName = "" } = {}) {
  if (share?.kind === "settlement") {
    const v = settlementCardView(share.payload, { mine, senderName });
    return ["정산 공유 카드", mine ? "" : `${senderLabel(senderName)}이 공유`, v.month, v.summary.text, ...v.lines.map((l) => l.text), v.moreCount ? `외 ${v.moreCount}건` : ""].filter(Boolean).join(", ");
  }
  const v = eventCardView(share?.payload);
  return ["일정 공유 카드", v.badge, v.title, v.when, v.place ? `장소 ${v.place}` : "", v.withText].filter(Boolean).join(", ");
}
