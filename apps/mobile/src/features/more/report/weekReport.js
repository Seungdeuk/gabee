// 마이 > AI 리포트: 한 주 집계 순수 함수. 날짜는 모두 KST(UTC+9) 고정, 주는 월~일.
// React/RN 에 의존하지 않아 Node 테스트로 돌린다.

export const MAX_WEEKS_BACK = 8;

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/**
 * 숫자를 두 자리 문자열로 만든다.
 * @param {number} n
 * @returns {string}
 */
const pad2 = (n) => String(n).padStart(2, "0");

/**
 * epoch 밀리초를 KST 달력 날짜로 바꾼다.
 * @param {number} ms
 * @returns {string} "YYYY-MM-DD"
 */
function kstDateOf(ms) {
  return new Date(ms + KST_OFFSET_MS).toISOString().slice(0, 10);
}

/**
 * "YYYY-MM-DD" 를 UTC 자정 밀리초로 바꾼다(달력 계산용).
 * @param {string} date
 * @returns {number}
 */
function dateToUtcMs(date) {
  const [y, m, d] = date.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/**
 * 날짜에 일 수를 더한다.
 * @param {string} date "YYYY-MM-DD"
 * @param {number} days
 * @returns {string} "YYYY-MM-DD"
 */
function addDays(date, days) {
  return new Date(dateToUtcMs(date) + days * DAY_MS).toISOString().slice(0, 10);
}

/**
 * 날짜의 요일 한 글자(일~토)를 돌려준다.
 * @param {string} date "YYYY-MM-DD"
 * @returns {string}
 */
function weekdayOf(date) {
  return WEEKDAYS[new Date(dateToUtcMs(date)).getUTCDay()];
}

/**
 * KST 기준 오늘 날짜.
 * @param {number} [now] epoch 밀리초
 * @returns {string} "YYYY-MM-DD"
 */
export function todayKst(now = Date.now()) {
  return kstDateOf(now);
}

/**
 * 기준 시각에서 offset 주 떨어진 월~일 범위.
 * @param {number} [now] epoch 밀리초
 * @param {number} [offset] 0 이번 주, -1 지난주 ...
 * @returns {{ start: string, end: string, label: string, title: string, offset: number, isCurrent: boolean }}
 */
export function weekRange(now = Date.now(), offset = 0) {
  const today = todayKst(now);
  const dow = new Date(dateToUtcMs(today)).getUTCDay(); // 0=일
  const sinceMonday = (dow + 6) % 7;
  const start = addDays(today, -sinceMonday + offset * 7);
  const end = addDays(start, 6);
  const [, sm, sd] = start.split("-").map(Number);
  const [, em, ed] = end.split("-").map(Number);
  const label = sm === em ? `${sm}월 ${sd}일 ~ ${ed}일` : `${sm}월 ${sd}일 ~ ${em}월 ${ed}일`;
  let title = `${-offset}주 전`;
  if (offset === 0) title = "이번 주";
  else if (offset === -1) title = "지난주";
  return { start, end, label, title, offset, isCurrent: offset === 0 };
}

/**
 * 더 이전 주로 갈 수 있는지.
 * @param {number} offset
 * @returns {boolean}
 */
export const canGoBack = (offset) => offset > -MAX_WEEKS_BACK;

/**
 * 더 최근 주로 갈 수 있는지(미래 주는 없다).
 * @param {number} offset
 * @returns {boolean}
 */
export const canGoForward = (offset) => offset < 0;

/**
 * 시작·종료 시각 문자열을 화면 표기로 바꾼다.
 * @param {string | null | undefined} startTime "HH:MM:SS" 또는 null
 * @param {string | null | undefined} endTime "HH:MM:SS" 또는 null
 * @returns {string} "종일" 또는 "오후 4:00"
 */
export function formatTime(startTime, endTime) {
  if (!startTime) return "종일";
  const [h, m] = startTime.split(":").map(Number);
  if (h === 0 && m === 0 && typeof endTime === "string" && endTime.startsWith("23:59")) {
    return "종일";
  }
  const period = h < 12 ? "오전" : "오후";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${period} ${h12}:${pad2(m)}`;
}

/**
 * 문서 생성 시각(ISO)을 KST 날짜로 바꾼다. 시간대 표시가 없으면 UTC 로 본다.
 * @param {string | null | undefined} createdAt
 * @returns {string | null} "YYYY-MM-DD"
 */
function docKstDate(createdAt) {
  if (!createdAt) return null;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(createdAt);
  const iso = createdAt.replace(/(\.\d{3})\d+/, "$1"); // 6자리 소수 초는 앱 엔진이 못 읽을 수 있어 밀리초까지만 쓴다
  const ms = Date.parse(hasZone ? iso : `${iso}Z`);
  return Number.isNaN(ms) ? null : kstDateOf(ms);
}

/**
 * 일정 두 건의 정렬 비교(날짜, 시작 시각, 종일이 먼저).
 * @param {object} a
 * @param {object} b
 * @returns {number}
 */
function compareEvents(a, b) {
  if (a.start_date !== b.start_date) return a.start_date < b.start_date ? -1 : 1;
  const ta = a.start_time || "";
  const tb = b.start_time || "";
  if (ta === tb) return 0;
  return ta < tb ? -1 : 1;
}

/**
 * 가비 한마디를 만든다.
 * @param {object} p 집계 값 묶음
 * @returns {string}
 */
function buildLine({ isCurrent, P, state, sharedCount, todoTotal, todoDone, docCount, docsFailed, docsPending }) {
  if (state === "all_empty") {
    return isCurrent
      ? "이번 주는 아직 가족이 공유한 기록이 없어요. 일정이나 할 일을 등록하고 문서를 공유하면 여기에 모아 보여 드릴게요."
      : `${P}에는 가족이 공유한 기록이 없었어요.`;
  }
  const parts = [];
  if (sharedCount > 0) {
    parts.push(
      isCurrent ? `이번 주 공유 일정은 ${sharedCount}건이에요.` : `${P} 공유 일정은 ${sharedCount}건이었어요.`,
    );
  } else {
    parts.push(isCurrent ? "이번 주는 공유 일정이 없어요." : `${P}는 공유 일정이 없었어요.`);
  }
  if (todoTotal > 0) {
    parts.push(
      todoDone === todoTotal
        ? `할 일 ${todoTotal}건을 모두 끝냈어요.`
        : `할 일은 ${todoTotal}건 중 ${todoDone}건 끝냈어요.`,
    );
  }
  if (docsPending) {
    // 문서를 처음 받는 중: 문서 문장은 아예 넣지 않는다
  } else if (docsFailed) {
    parts.push("공유한 문서는 지금 확인할 수 없어요.");
  } else if (docCount > 0) {
    parts.push(isCurrent ? `공유한 문서가 ${docCount}건 있어요.` : `공유한 문서는 ${docCount}건이었어요.`);
  }
  return parts.join(" ");
}

/**
 * 인사이트(사실만, 최대 3개)를 만든다. 아직 보지 않은 문서가 있으면(`docUnseen > 0`) 할 일 다음에 넣는다.
 * @param {object} p 집계 값 묶음
 * @returns {{ key: string, text: string, action?: "schedule" }[]}
 */
function buildInsights({ isCurrent, P, today, todoTotal, todoLeft, docUnseen, shared }) {
  const out = [];
  const unseenDocs = docUnseen > 0
    ? { key: "doc_unseen", text: `${P} 올라온 문서 중 아직 보지 않은 것이 ${docUnseen}건 있어요.` }
    : null;
  if (isCurrent) {
    if (todoLeft > 0) {
      out.push({ key: "todo_left", text: `이번 주 남은 할 일이 ${todoLeft}건 있어요.`, action: "schedule" });
    }
    if (unseenDocs) out.push(unseenDocs);
    const next = shared.find((e) => e.start_date >= today);
    if (next) {
      let text = `가장 가까운 일정은 ${weekdayOf(next.start_date)}요일 ${next.title}이에요.`;
      if (next.start_date === today) text = `오늘 ${next.title} 일정이 있어요.`;
      else if (next.start_date === addDays(today, 1)) text = `내일 ${next.title} 일정이 있어요.`;
      out.push({ key: "next_event", text });
    }
  } else {
    if (todoLeft > 0) {
      out.push({
        key: "todo_left",
        text: `${P} 할 일 ${todoTotal}건 중 ${todoLeft}건은 아직 완료되지 않았어요.`,
        action: "schedule",
      });
    } else if (todoTotal > 0) {
      out.push({ key: "todo_done", text: `${P} 할 일 ${todoTotal}건을 모두 끝냈어요.` });
    }
    if (unseenDocs) out.push(unseenDocs);
    const perDay = new Map();
    for (const e of shared) perDay.set(e.start_date, (perDay.get(e.start_date) || 0) + 1);
    let bestDate = null;
    let bestN = 0;
    for (const [date, n] of perDay) {
      if (n > bestN || (n === bestN && date < bestDate)) {
        bestDate = date;
        bestN = n;
      }
    }
    if (bestN >= 2) {
      out.push({ key: "busiest", text: `${weekdayOf(bestDate)}요일에 공유 일정이 가장 많았어요(${bestN}건).` });
    }
  }
  return out.slice(0, 3); // 항목이 늘어도 카드가 길어지지 않게 하는 안전장치(지금은 각 분기가 3개를 넘지 않는다)
}

/**
 * 한 주 리포트를 만든다.
 * @param {{ events: object[], docs: object[] | null, range: ReturnType<typeof weekRange>, today: string, docsPending?: boolean }} args
 *   events 는 필수, docs 가 null 이면 문서를 불러오지 못한 것. docsPending 이 true 면 문서를 처음 받는 중이라
 *   실패가 아니다(docCount null, 문서 문장 없음, 문서 0건으로 확정하지 않으므로 all_empty 가 되지 않는다).
 * @returns {{
 *   isCurrent: boolean, state: "ok" | "events_empty" | "all_empty",
 *   sharedCount: number, todoTotal: number, todoDone: number,
 *   docCount: number | null, docUnseen: number | null, docsFailed: boolean,
 *   listTitle: string, listTotal: number,
 *   list: { id: *, title: string, date: string, weekday: string, day: number, timeText: string, meta: string }[],
 *   insights: { key: string, text: string, action?: "schedule" }[], line: string
 * }}
 */
export function buildReport({ events, docs, range, today, docsPending = false }) {
  const { start, end, isCurrent, offset } = range;
  const inWeek = (d) => typeof d === "string" && d >= start && d <= end;
  let P = "그 주";
  if (offset === 0) P = "이번 주";
  else if (offset === -1) P = "지난주";

  const sharedAll = (events || [])
    .filter((e) => e.shared === true && inWeek(e.start_date))
    .sort(compareEvents);
  const shared = sharedAll.filter((e) => e.kind === 1);
  const todos = sharedAll.filter((e) => e.kind === 2);
  const todoTotal = todos.length;
  const todoDone = todos.filter((e) => e.checked === true).length;
  const todoLeft = todoTotal - todoDone;

  const docsFailed = docs == null && !docsPending;
  const weekDocs = docsPending || docs == null
    ? null
    : docs.filter((d) => d.sensitivity !== "sensitive" && inWeek(docKstDate(d.created_at)));
  const docCount = weekDocs ? weekDocs.length : null;
  // 내가 아직 보지 않은 문서 수: 서버가 `seen` 을 주지 않으면(구버전 서버) 알 수 없으므로 null
  const docUnseen = weekDocs && weekDocs.every((d) => typeof d.seen === "boolean")
    ? weekDocs.filter((d) => d.seen === false).length
    : null;

  const sharedCount = shared.length;
  let state = "ok";
  if (sharedCount === 0) {
    state = todoTotal === 0 && docCount === 0 ? "all_empty" : "events_empty";
  }

  const target = isCurrent ? shared.filter((e) => e.start_date >= today) : shared;
  const list = target.slice(0, isCurrent ? 3 : 5).map((e) => {
    const timeText = formatTime(e.start_time, e.end_time);
    return {
      id: e.id,
      title: e.title,
      date: e.start_date,
      weekday: weekdayOf(e.start_date),
      day: Number(e.start_date.slice(8, 10)),
      timeText,
      meta: `${timeText} · 가족 공유`,
    };
  });

  return {
    isCurrent,
    state,
    sharedCount,
    todoTotal,
    todoDone,
    docCount,
    docUnseen,
    docsFailed,
    listTitle: isCurrent ? "이번 주 남은 공유 일정" : "그 주의 공유 일정",
    listTotal: target.length,
    list,
    insights: buildInsights({ isCurrent, P, today, todoTotal, todoLeft, docUnseen, shared }),
    line: buildLine({ isCurrent, P, state, sharedCount, todoTotal, todoDone, docCount, docsFailed, docsPending }),
  };
}
