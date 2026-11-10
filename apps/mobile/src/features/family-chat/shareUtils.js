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

// ---------------------------------------------------------------------------------------------
// 공유 시트(보내기): 항목 구성, 확인창 문구, 오류 문구

/** 일정 목록을 받아 오지 못했을 때 시트에 보이는 문구. */
export const SHARE_LOAD_ERROR = "일정을 불러오지 못했어요. 다시 시도해 주세요";

/** 시트가 닫힌 뒤 다음 창을 열기까지 더 기다리는 시간(밀리초). ai-assistant 의 ChatInput 선례와 같다. 창 두 개가 겹쳐 뜨면 iOS 에서 열리지 않는 경우가 있다. */
export const SHEET_HANDOFF_MS = 500;

/**
 * 시트(Modal)를 닫은 직후가 아니라 닫힘이 끝난 뒤에 다음 일을(보통 다른 Modal 을 여는 것) 실행한다: 상호작용(닫는 애니메이션)이 끝나면 delay 만큼 더 기다렸다가 한 번 실행한다.
 * 화면 쪽은 runAfterInteractions 에 InteractionManager.runAfterInteractions 를 넘기고, 시험은 가짜 함수를 넘긴다(기본은 즉시).
 * @param {() => void} fn 닫힘이 끝난 뒤 실행할 일
 * @param {{ runAfterInteractions?: (cb: () => void) => void, setTimer?: (cb: () => void, ms: number) => unknown, clearTimer?: (id: unknown) => void, delay?: number }} [deps]
 * @returns {() => void} 취소 함수(실행 전에 부르면 실행하지 않는다, 여러 번 불러도 된다)
 */
export function scheduleAfterSheetClose(fn, { runAfterInteractions = (cb) => cb(), setTimer = setTimeout, clearTimer = clearTimeout, delay = SHEET_HANDOFF_MS } = {}) {
  let canceled = false;
  let timer = null;
  runAfterInteractions(() => {
    if (canceled) return;
    timer = setTimer(() => {
      timer = null;
      if (!canceled) fn();
    }, delay);
  });
  return () => {
    canceled = true;
    if (timer != null) {
      clearTimer(timer);
      timer = null;
    }
  };
}

/** 정산 시트에 보일 달 수(이번 달부터 거슬러). 월 목록 API 가 없어 앱이 만든다. */
export const SHARE_MONTHS_SHOWN = 6;

/** 확인창 고지 문구(가족방·1:1 방 같음). 정산 금액은 앱이 계산하지 않아 확인창에 금액은 없다. */
export const SHARE_NOTICE = {
  event: "이 일정이 이 채팅방 사람들에게 보이고, @가비·AI 도우미가 답변에 쓸 수 있어요.",
  settlement: "정산 금액이 이 채팅방 사람들에게 보이고, @가비·AI 도우미가 답변에 쓸 수 있어요.",
};

const SHEET_COPY = {
  event: { title: "공유할 일정 고르기", hint: "내 일정과 할 일 중 오늘 이후의 것만 보여요", empty: "공유할 일정이 없어요. 오늘 이후의 내 일정만 보낼 수 있어요" },
  settlement: { title: "공유할 정산 달 고르기", hint: "정산 내역이 있는 달만 보낼 수 있어요", empty: "공유할 달이 없어요" },
};

/**
 * 공유 시트의 제목·안내·빈 상태 문구.
 * @param {"event" | "settlement" | null | undefined} kind
 * @returns {{ title: string, hint: string, empty: string }}
 */
export const shareSheetCopy = (kind) => SHEET_COPY[kind] ?? { title: "", hint: "", empty: "" };

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * 일정의 날짜(YYYY-MM-DD): start_date 가 있으면 그것, 없으면 starts_at(ISO 시각)의 한국 시간(Asia/Seoul, UTC+9) 날짜.
 * 서버 카드(`chat_share.py` 의 `_date_of`)와 같은 규칙이다. 둘 다 없거나 시각이 틀리면 null.
 * @param {{ start_date?: string | null, starts_at?: string | null } | null | undefined} event listScheduleEvents 의 한 줄
 * @returns {string | null}
 */
export function shareEventDate(event) {
  if (!event) return null;
  if (typeof event.start_date === "string" && event.start_date) return event.start_date;
  if (typeof event.starts_at !== "string" || !event.starts_at) return null;
  const iso = /(Z|[+-]\d{2}:?\d{2})$/i.test(event.starts_at) ? event.starts_at : `${event.starts_at}Z`; // 오프셋이 없으면 UTC(기기 시간대로 읽지 않는다)
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return null;
  return new Date(ms + KST_OFFSET_MS).toISOString().slice(0, 10); // UTC 필드로 읽으면 한국 날짜가 된다
}

/**
 * 일정 시트의 항목: 오늘 이후(오늘 포함)의 약속·할 일만, 날짜·시간 오름차순(시간 없는 것이 그날 먼저).
 * 날짜는 shareEventDate 로 구한다(start_date 가 비어 있는 옛 일정은 starts_at 의 한국 날짜). 날짜를 알 수 없는 일정·끝낸 할 일·모르는 종류는 뺀다.
 * @param {{ id: string, title?: string, kind?: number, start_date?: string | null, starts_at?: string | null, start_time?: string | null, checked?: boolean }[] | null | undefined} events listScheduleEvents 결과
 * @param {string} today YYYY-MM-DD(기기의 오늘)
 * @returns {{ key: string, ref: string, title: string, line: string, badge: "약속" | "할 일" }[]}
 */
export function buildShareEventItems(events, today) {
  const rows = (Array.isArray(events) ? events : [])
    .filter((e) => e && (e.kind === 1 || e.kind === 2) && !(e.kind === 2 && e.checked))
    .map((e) => ({ e, date: shareEventDate(e) }))
    .filter((r) => r.date !== null && r.date >= today);
  rows.sort((a, b) => a.date.localeCompare(b.date) || String(a.e.start_time ?? "").localeCompare(String(b.e.start_time ?? "")));
  return rows.map(({ e, date }) => ({
    key: `e:${e.id}`,
    ref: e.id,
    title: String(e.title ?? "").trim() || "(제목 없음)",
    line: [formatShareDate(date), formatShareTime(e.start_time, null)].filter(Boolean).join(" · "),
    badge: e.kind === 2 ? "할 일" : "약속",
  }));
}

/**
 * 정산 시트의 항목: 기기 기준 이번 달부터 거슬러 올라간 달들(ref 는 서버가 받는 YYYY-MM).
 * @param {Date} [now]
 * @param {number} [count]
 * @returns {{ key: string, ref: string, title: string, line: string, badge: "정산" }[]}
 */
export function recentShareMonths(now = new Date(), count = SHARE_MONTHS_SHOWN) {
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const ref = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    return { key: `m:${ref}`, ref, title: formatShareMonth(ref), line: "", badge: "정산" };
  });
}

/**
 * 공유 확인창 문구: 제목·본문(고지 포함)·확인 버튼 라벨. 일정은 제목·날짜를 보여 주고, 정산은 달만 보인다.
 * @param {"event" | "settlement"} kind
 * @param {{ title: string, line: string } | null | undefined} item 고른 시트 항목
 * @returns {{ title: string, message: string, confirmLabel: string }}
 */
export function shareConfirmCopy(kind, item) {
  if (kind === "settlement") return { title: `${item?.title ?? ""} 정산을 공유할까요?`.trim(), message: SHARE_NOTICE.settlement, confirmLabel: "공유하기" };
  const what = [item?.title, item?.line].filter(Boolean).join("\n");
  return { title: "이 일정을 공유할까요?", message: `${what ? `${what}\n\n` : ""}${SHARE_NOTICE.event}`, confirmLabel: "공유하기" };
}

/**
 * 초를 "30초" / "2분" 으로(messages.js 의 waitText 와 같은 형식).
 * @param {number} seconds
 * @returns {string}
 */
const waitText = (seconds) => (seconds < 60 ? `${seconds}초` : `${Math.ceil(seconds / 60)}분`);

/**
 * 공유 보내기 오류를 사용자 문장으로(카드 내용은 넣지 않는다). 상태·코드로 알아본다.
 * 404 는 서버가 방 접근 불가·내 일정 아님·정산 내역 없음을 모두 `not_found` 로 돌려줘 오류 코드로는 가를 수 없다.
 * 그래서 보내려던 종류(kind)를 알면 그 종류의 가장 흔한 사유로 안내하고(방이 없는 드문 경우도 같은 문구), 모르면 기존 문구를 쓴다.
 * @param {{ status?: number, code?: string, retryAfter?: number } | null | undefined} error
 * @param {"event" | "settlement" | null} [kind] 보내려던 카드 종류(선택)
 * @returns {string}
 */
export function shareSendErrorMessage(error, kind) {
  const { status, code } = error ?? {};
  if (status === 404) {
    if (kind === "settlement") return "그 달에는 정산 내역이 없어요";
    if (kind === "event") return "이미 지워졌거나 내 일정이 아니에요";
    return "공유할 내용을 찾지 못했어요. 이미 지워졌거나 정산 내역이 없는 달일 수 있어요";
  }
  if (code === "invalid_month") return "정산 달이 올바르지 않아요. 다시 골라 주세요";
  if (code === "share_too_large") return "내용이 너무 길어서 공유할 수 없어요";
  if (code === "peer_left_room" || status === 409) return "상대방이 나가서 메시지를 보낼 수 없어요";
  if (status === 429) return `공유를 너무 자주 했어요. 잠시 후 다시 해 주세요${error.retryAfter ? ` (${waitText(error.retryAfter)} 뒤에 다시 시도할 수 있어요)` : ""}`;
  if (status === 503 || code === "share_unavailable" || code === "schema_not_ready") return "지금은 공유할 수 없어요. 잠시 후 다시 시도해 주세요";
  if (code === "network_error" || status === 0) return "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요";
  return "공유하지 못했어요. 잠시 후 다시 시도해 주세요";
}
