// 데일리 체크의 순수 로직. 화면·저장소와 떨어져 있어 node:test 로 시험한다(tests/schedule_daily.test.js).
// 요일 키는 월요일부터 시작한다(화면의 월~일 순서와 같다). 날짜 키는 "YYYY-MM-DD", 시각은 "HH:MM"(24시간)이다.
import { avatarPalette, colors } from "@/theme/index";

export const WEEK_DAYS = [
  { key: "mon", label: "월" },
  { key: "tue", label: "화" },
  { key: "wed", label: "수" },
  { key: "thu", label: "목" },
  { key: "fri", label: "금" },
  { key: "sat", label: "토" },
  { key: "sun", label: "일" },
];

const DAY_KEYS = WEEK_DAYS.map((d) => d.key);
export const ALL_DAYS = [...DAY_KEYS];
export const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"];
export const WEEKEND = ["sat", "sun"];

// 길게 누르는 시간(ms). 줄 메뉴(수정·삭제)를 여는 꾹 누르기와, 가족 순서·편집 화면에서 줄을 끌기 시작하는 꾹 누르기가 같은 값을 쓴다.
export const ROW_MENU_HOLD_MS = 450;
// 꾹 누르기 전에 이 거리(px)를 넘게 움직이면 꾹 누르기를 취소하고 스크롤이 받는다.
export const HOLD_CANCEL_PX = 10;

/**
 * 꾹 누르기 제스처의 판정(순수 함수).
 * - 꾹 누르기 시간이 끝났으면(armed) 같은 터치로 끈다("activate").
 * - 아직 꾹 누르는 중인데 취소 거리를 넘게 움직였으면 실패해서 스크롤이 받는다("fail").
 * - 그 밖이면 기다린다("wait").
 */
export function holdDecision({ armed, moved, cancelPx = HOLD_CANCEL_PX }) {
  if (armed) return "activate";
  if (moved > cancelPx) return "fail";
  return "wait";
}

export const ROW_HEIGHT = 72;
export const ROW_GAP = 10;
export const TAB_ROW_HEIGHT = 64;
export const TAB_ROW_GAP = 12;

const pad = (n) => String(n).padStart(2, "0");

/** "YYYY-MM-DD" 의 요일 키(mon~sun). */
export function weekdayKeyOf(dateKey) {
  const [y, m, d] = dateKey.split("-").map(Number);
  const jsDay = new Date(y, m - 1, d).getDay(); // 일요일이 0
  return DAY_KEYS[(jsDay + 6) % 7];
}

/** "11월 2일 월요일" 같은 머리글 글자. */
export function formatDayLabel(dateKey) {
  const [, m, d] = dateKey.split("-").map(Number);
  const weekLabel = WEEK_DAYS.find((x) => x.key === weekdayKeyOf(dateKey)).label;
  return `${m}월 ${d}일 ${weekLabel}요일`;
}

/** 항목의 반복 요일에 이 날짜가 들어 있는가. */
export function isScheduledOn(item, dateKey) {
  return Array.isArray(item.days) && item.days.includes(weekdayKeyOf(dateKey));
}

/** 오늘(이 날짜) 목록에 나올 항목만 거른다. 순서는 그대로다. */
export function todayItemsOf(items, dateKey) {
  return items.filter((item) => isScheduledOn(item, dateKey));
}

export const isCount = (item) => item.type === "count";

/**
 * 완료 판정. 한 번 체크는 done 이 켜졌는지, 횟수 세기는 횟수가 하루 목표에 닿았는지로 본다.
 * @param {{ type: string, goal: number }} item
 * @param {{ done?: boolean, count?: number } | undefined} entry
 */
export function isDone(item, entry) {
  if (!entry) return false;
  if (isCount(item)) return (entry.count ?? 0) >= item.goal;
  return Boolean(entry.done);
}

/** 한 번 체크를 누른다(켜져 있으면 끈다). now 는 "HH:MM". */
export function applyCheck(entry, now) {
  const done = !entry?.done;
  return { done, count: 0, doneAt: done ? now : null };
}

// 횟수 상한은 실수로 너무 많이 눌렀을 때를 막는 값이다. 목표를 넘겨서 계속 기록할 수 있다.
export const COUNT_MAX = 9999;

/**
 * 횟수를 delta 만큼 바꾼다. 0 과 COUNT_MAX 사이에 머문다. 목표를 넘겨도 계속 올라간다(완료는 count >= goal).
 * 목표에 처음 닿은 시각을 기록한다(이미 완료였으면 그 시각을 그대로 둔다). 목표를 줄여도 count 는 깎지 않는다.
 */
export function applyStep(item, entry, delta, now) {
  const next = Math.max(0, Math.min(COUNT_MAX, (entry?.count ?? 0) + delta));
  const done = next >= item.goal;
  return { done, count: next, doneAt: done ? (entry?.doneAt ?? now) : null };
}

/** 횟수 칩 글자: "현재/목표". 목표를 넘기면 "10/8" 처럼 그대로 보인다. */
export function countChipText(entry, goal) {
  return `${entry?.count ?? 0}/${goal}`;
}

/**
 * 전화 앱에서 앱으로 돌아왔을 때 통화 뒤 시트를 띄울지. 오늘 목록에 "안부 전화" 습관이 있고 오늘 아직 완료가 아닐 때만 띄운다.
 * 습관이 없거나(요일에 안 맞음 포함) 이미 완료면 false.
 * @param {object[]} items 전체 습관
 * @param {Record<string, object>} entries 오늘 기록(습관 id → 기록)
 * @param {string} dateKey 오늘 날짜 키
 */
export function shouldShowCallDone(items, entries, dateKey) {
  const target = findCallItem(items, dateKey);
  if (!target) return false;
  return !isDone(target, entries[target.id]);
}

/**
 * 완료 수 / 전체 수 와 퍼센트.
 * @param {object[]} items
 * @param {(item: object) => object | undefined} entryOf 항목의 오늘 기록
 */
export function progressOf(items, entryOf) {
  const total = items.length;
  const done = items.filter((item) => isDone(item, entryOf(item))).length;
  return { done, total, pct: total ? Math.round((done / total) * 100) : 0 };
}

/** 가족에게 보이기가 켜진 항목 중 오늘 해당하는 것. 각 항목에 entry(오늘 기록)가 들어 있다고 본다. */
export function familyRowsOf(items, dateKey) {
  return items.filter((item) => item.shareWithFamily && isScheduledOn(item, dateKey));
}

/** 오늘 완료된 항목 중 가장 늦은 완료 시각("HH:MM"), 없으면 null. */
export function lastRecordOf(rows) {
  const times = rows
    .filter((row) => isDone(row, row.entry) && row.entry?.doneAt)
    .map((row) => row.entry.doneAt)
    .sort();
  return times.length ? times[times.length - 1] : null;
}

/** 탭 라벨. "엄마 3/3" 형식. */
export const tabLabel = (name, done, total) => `${name} ${done}/${total}`;

/**
 * 가족 탭 순서와 숨김 목록을 가족 구성원 목록에 맞춘다. 나(me)는 탭 줄 맨 앞에 고정이라 여기 들어오지 않는다.
 * 새로 생긴 구성원은 뒤에 붙고, 없어진 구성원은 빠진다.
 * @param {{ order?: string[], hidden?: string[] } | null | undefined} saved
 * @param {string[]} familyIds 가족 구성원 id(나 제외)
 * @returns {{ order: string[], hidden: string[] }}
 */
export function normalizeTabs(saved, familyIds) {
  const known = new Set(familyIds);
  const order = [];
  for (const id of [...(saved?.order ?? []), ...familyIds]) {
    if (known.has(id) && !order.includes(id)) order.push(id);
  }
  const hidden = [...new Set(saved?.hidden ?? [])].filter((id) => known.has(id));
  return { order, hidden };
}

/** 탭 줄에 보이는 가족 id(순서대로, 숨긴 것 제외). */
export const visibleTabIds = (tabs) => tabs.order.filter((id) => !tabs.hidden.includes(id));

export function hideTab(tabs, id) {
  return tabs.hidden.includes(id) ? tabs : { ...tabs, hidden: [...tabs.hidden, id] };
}

export function showTab(tabs, id) {
  return { ...tabs, hidden: tabs.hidden.filter((x) => x !== id) };
}

// ── 끌어서 순서 바꾸기 ──────────────────────────────────────────────

/**
 * 항목 목록에서 id 를 위(dir -1)·아래(dir 1)로 한 칸 옮긴 새 배열. 첫 칸의 위, 끝 칸의 아래는 그대로(같은 배열).
 * 편집 화면의 화살표와 가족 순서 바꾸기 화면이 같은 규칙을 쓴다.
 */
export function moveItemOne(list, id, dir) {
  const from = list.findIndex((x) => x.id === id);
  return moveIndex(list, from, from + dir);
}

/** 위/아래 화살표 비활성: 첫 칸의 위, 끝 칸의 아래는 꺼진다. 없는 id 도 꺼진다. */
export function itemArrowDisabled(list, id, dir) {
  const i = list.findIndex((x) => x.id === id);
  if (i < 0) return true;
  return dir < 0 ? i === 0 : i === list.length - 1;
}

/** 목록에서 from 자리의 것을 to 자리로 옮긴 새 배열. 범위 밖이거나 같으면 그대로 돌려준다. */
export function moveIndex(list, from, to) {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = list.slice();
  const [picked] = next.splice(from, 1);
  next.splice(to, 0, picked);
  return next;
}

/**
 * 전체 순서 중 보이는 id 들의 자리에 nextVisible 을 차례로 채운다. 보이지 않는 id 는 제자리다.
 * 예: order [a,x,b], visible [a,b] → nextVisible [b,a] 이면 [b,x,a].
 */
export function placeVisible(order, visibleIds, nextVisible) {
  const visible = new Set(visibleIds);
  let k = 0;
  return order.map((id) => (visible.has(id) ? nextVisible[k++] : id));
}

/** 가족 탭 순서에서 보이는 탭끼리 from 번째를 to 번째로 옮긴다(숨긴 탭은 제자리). */
export function reorderTabs(tabs, from, to) {
  const visible = visibleTabIds(tabs);
  const order = placeVisible(tabs.order, visible, moveIndex(visible, from, to));
  return { ...tabs, order };
}

/**
 * 보이는 가족 탭 한 칸 위(dir -1)·아래(dir 1)로 옮긴다. 첫 칸에서 위, 끝 칸에서 아래는 그대로(같은 객체).
 * 나(고정)는 여기 들어오지 않는다.
 */
export function moveTab(tabs, id, dir) {
  const visible = visibleTabIds(tabs);
  const from = visible.indexOf(id);
  const to = from + dir;
  if (from < 0 || to < 0 || to >= visible.length) return tabs;
  return reorderTabs(tabs, from, to);
}

/** 위·아래 화살표 비활성 여부: 맨 위 칸은 위가, 맨 아래 칸은 아래가 꺼진다. */
export function tabArrowDisabled(tabs, id, dir) {
  const visible = visibleTabIds(tabs);
  const i = visible.indexOf(id);
  if (i < 0) return true;
  return dir < 0 ? i === 0 : i === visible.length - 1;
}

/**
 * 줄 메뉴(수정/삭제 카드)의 위치: 줄의 점 세 개 버튼 아래에 살짝 겹치게 붙인다.
 * 줄의 맨 아래 줄이면 위로 뒤집어서 화면 밖으로 나가지 않게 한다.
 * @returns {number} 목록 안에서의 top(px)
 */
export function rowMenuTop(index, count, stride, rowHeight, menuHeight) {
  const rowTop = index * stride;
  const below = rowTop + 44;
  const isLast = count > 1 && index === count - 1;
  return isLast ? rowTop + rowHeight - menuHeight + 8 : below;
}

/**
 * 끄는 중인 줄이 놓일 자리(인덱스). 처음 자리(from)에서 손가락이 움직인 만큼(dy) 줄 간격(stride)으로 환산해 0~count-1 안에 가둔다.
 */
export function dragTargetIndex(from, dy, stride, count) {
  if (count <= 0 || stride <= 0) return 0;
  const raw = from + Math.round(dy / stride);
  return Math.max(0, Math.min(count - 1, raw));
}

/**
 * 끌지 않는 줄이 자리를 비켜 줄 만큼의 세로 이동(px). 끌던 줄이 from 에서 to 로 가면,
 * 그 사이에 있던 줄들이 한 칸씩 반대쪽으로 밀린다.
 */
export function shiftOffset(index, from, to, stride) {
  if (from === to) return 0;
  if (from < to && index > from && index <= to) return -stride;
  if (to < from && index >= to && index < from) return stride;
  return 0;
}

// ── 반복 요일 빠른 선택 ─────────────────────────────────────────────

export const DAY_PRESETS = [
  { key: "all", label: "모두" },
  { key: "weekdays", label: "평일" },
  { key: "weekend", label: "주말" },
  { key: "none", label: "해제" },
];

/** 빠른 선택 칩을 누르면 바뀌는 요일 목록. */
export function presetDays(key) {
  if (key === "weekdays") return [...WEEKDAYS];
  if (key === "weekend") return [...WEEKEND];
  if (key === "all") return [...ALL_DAYS];
  return [];
}

/** 지금 고른 요일이 어느 빠른 선택과 같은지(같지 않으면 null). 칩의 눌린 표시에 쓴다. */
export function matchDayPreset(days) {
  const set = new Set(days);
  for (const preset of DAY_PRESETS) {
    const want = presetDays(preset.key);
    if (want.length === set.size && want.every((d) => set.has(d))) return preset.key;
  }
  return null;
}

/** "2" "8잔" "30분" → { goal, unit }. 1 이상 4자리 이하의 숫자가 앞에 와야 한다. 안 맞으면 null. */
export function parseGoal(text) {
  const m = String(text ?? "").trim().match(/^(\d{1,4})\s*(.*)$/);
  if (!m) return null;
  const goal = Number(m[1]);
  if (goal < 1) return null;
  return { goal, unit: m[2].trim() };
}

export const formatGoal = (goal, unit = "") => `${goal}${unit}`;

/** 하루 목표 글자를 delta 만큼 바꾼 글자. 단위는 그대로 둔다. 1 아래로는 내려가지 않는다. */
export function stepGoalText(text, delta) {
  const parsed = parseGoal(text) ?? { goal: 1, unit: "" };
  return formatGoal(Math.max(1, Math.min(9999, parsed.goal + delta)), parsed.unit);
}

// 입력 글자 수 상한(앱 한도). 서버 한도(이름 60·단위 10·한마디 100, apps/api/app/features/schedule/check_schemas.py)보다
// 앱 한도를 더 좁게 둔 것(사용자 결정)이다. 서버 한도를 넘지 않으므로 서버 쪽 422 는 이 칸에서 나오지 않는다.
export const NAME_MAX = 20;
export const UNIT_MAX = 10;
export const CHEER_TEXT_MAX = 50;

/** 항목 저장 전 검사. 첫 번째 잘못된 점 하나만 알려 준다. 이름은 서버처럼 자르기 전 글자 수로 센다. */
export function validateItem(draft) {
  if (!draft.name?.trim()) return { ok: false, error: "이름을 적어 주세요" };
  if (draft.name.length > NAME_MAX) return { ok: false, error: `이름은 ${NAME_MAX}자까지 쓸 수 있어요` };
  if (!draft.days?.length) return { ok: false, error: "반복할 요일을 하나 이상 골라 주세요" };
  if (draft.type === "count") {
    const parsed = parseGoal(draft.goalText);
    if (!parsed) return { ok: false, error: "하루 목표는 1 이상의 숫자로 적어 주세요" };
    if (parsed.unit.length > UNIT_MAX) return { ok: false, error: `단위는 ${UNIT_MAX}자까지 쓸 수 있어요` };
  }
  return { ok: true, error: "" };
}

/**
 * 전화 버튼을 보일지. 안드로이드는 canOpenURL 을 믿지 않고 항상 보인다(Android 11+ 는 패키지 공개 설정 때문에 tel: 확인이 거짓이 될 수 있다).
 * iOS 는 canOpenURL("tel:") 결과를 따른다. 확인 전(canOpen 이 null)에는 보인다.
 * @param {string} platform Platform.OS
 * @param {boolean | null} canOpen canOpenURL("tel:") 결과(아직 모르면 null)
 */
export function shouldShowCallButton(platform, canOpen) {
  if (platform === "android") return true;
  if (canOpen === null || canOpen === undefined) return true;
  return Boolean(canOpen);
}

/** 응원 한마디 검사: 빈 글자는 화면이 따로 알리므로 여기서는 글자 수만 본다. 문제없으면 "". */
export function cheerTextError(text) {
  if (String(text ?? "").length > CHEER_TEXT_MAX) return `한마디는 ${CHEER_TEXT_MAX}자까지 쓸 수 있어요`;
  return "";
}

/**
 * 화면 입력을 저장할 항목 모양으로 바꾼다. 요일은 월~일 순서로 정리하고, 한 번 체크는 목표 1·단위 없음이다.
 * @param {{ id?: string, name: string, type: "check" | "count", goalText?: string, days: string[], alarm?: boolean, shareWithFamily?: boolean }} draft
 */
export function buildItem(draft) {
  const count = draft.type === "count";
  const parsed = count ? parseGoal(draft.goalText) : null;
  return {
    id: draft.id,
    name: draft.name.trim(),
    type: count ? "count" : "check",
    goal: count ? parsed.goal : 1,
    unit: count ? parsed.unit : "",
    days: DAY_KEYS.filter((k) => draft.days.includes(k)),
    alarm: Boolean(draft.alarm),
    shareWithFamily: Boolean(draft.shareWithFamily),
  };
}

/** 반복 요일 줄 글자: 매일 / 평일 / 주말 / "월·수·금". */
export function daysLabel(days) {
  const set = new Set(days);
  if (ALL_DAYS.every((d) => set.has(d))) return "매일";
  if (set.size === WEEKDAYS.length && WEEKDAYS.every((d) => set.has(d))) return "평일";
  if (set.size === 2 && set.has("sat") && set.has("sun")) return "주말";
  return WEEK_DAYS.filter((d) => set.has(d.key))
    .map((d) => d.label)
    .join("·");
}

/**
 * 내 항목 편집 줄의 보조 글자. "체크"·"횟수" 단어는 쓰지 않는다.
 * 횟수 항목은 "하루 8잔 · 매일", 한 번 체크는 "매일" / "평일" / "주말" / "월·수·금".
 */
export function itemDescription(item) {
  // 횟수 항목은 주기를 먼저, 횟수를 다음에("매일 · 하루 30분")
  if (isCount(item)) return `${daysLabel(item.days)} · 하루 ${formatGoal(item.goal, item.unit)}`;
  return daysLabel(item.days);
}

/**
 * 항목 줄 아래 한 줄 글자.
 * @param {{ type: string, goal: number, unit: string }} item
 * @param {{ done?: boolean, count?: number, doneAt?: string | null } | undefined} entry
 * @param {{ family?: boolean }} [options] family 면 가족 탭 문구를 쓴다
 */
export function itemSubText(item, entry, { family = false } = {}) {
  if (isCount(item)) return `하루 ${formatGoal(item.goal, item.unit)} 목표`;
  if (isDone(item, entry)) return entry.doneAt ? `${formatClock(entry.doneAt)} 완료` : "완료";
  return family ? "아직 기록이 없어요" : "아직이에요";
}

/** "08:10" → "오전 8:10". 없으면 빈 글자. */
export function formatClock(hhmm) {
  if (!hhmm) return "";
  const [h, m] = hhmm.split(":").map(Number);
  const ampm = h < 12 ? "오전" : "오후";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${ampm} ${h12}:${pad(m)}`;
}

// ── 2차: 온보딩 · 응원 · 전화 (앱만, 서버 없음) ─────────────────────

/** "YYYY-MM-DD" 에서 n일 뒤(음수면 앞) 날짜 키. */
export function shiftDayKey(dateKey, n) {
  const [y, m, d] = dateKey.split("-").map(Number);
  const x = new Date(y, m - 1, d + n);
  return `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
}

/** 날짜 묶음 머리글: 오늘 / 어제 / "10월 30일". */
export function dateGroupLabel(dateKey, today) {
  if (dateKey === today) return "오늘";
  if (dateKey === shiftDayKey(today, -1)) return "어제";
  const [, m, d] = dateKey.split("-").map(Number);
  return `${m}월 ${d}일`;
}

export const CHEER_KINDS = [
  { key: "love", label: "사랑해요" },
  { key: "best", label: "최고예요" },
  { key: "well", label: "잘하셨어요" },
];

/** 한마디 고르기 문구 두 개. 직접 쓰기 칸이 비어 있으면 이 중 하나를 고른다. */
export const CHEER_MESSAGES = ["오늘도 다 챙기셨네요, 최고예요", "물 한 잔만 더 드시면 돼요"];

export const cheerKindLabel = (key) => CHEER_KINDS.find((k) => k.key === key)?.label ?? "";

/**
 * 응원 종류별 색. 사랑해요 = 복숭아, 최고예요 = 꿀, 잘하셨어요 = 연두.
 * bg 는 카드·선택 버튼 바탕, border 는 테두리와 아이콘 원, icon 은 원의 색(글자색은 colors.text 로 쓴다).
 * 꿀·연두 원색은 avatarPalette 의 칸을 그대로 쓴다.
 * @returns {{ bg: string, border: string, icon: string }}
 */
export function cheerTone(kind) {
  if (kind === "best") return { bg: "#E6F0F8", border: "#C9DDEE", icon: "#3A6E99", strong: "#3A6E99", text: "#3A6E99" };
  if (kind === "well") return { bg: "#FEF0CC", border: "#F2D58E", icon: "#B7791C", strong: "#B7791C", text: "#8A5A2B" };
  return { bg: "#FFEDE5", border: "#F6CDBE", icon: "#C2503A", strong: "#C2503A", text: "#C2503A" };
}

/**
 * 추천 항목. pool 에서 이미 있는 이름을 뺀 것 중 앞에서 count 개를 돌려준다(화면에는 3개).
 * 추천 칩 글자: 목표가 있으면 "산책하기 · 30분", 없으면 이름만.
 * @param {{ name: string, goal?: number, unit?: string }[]} pool
 * @param {string[]} existingNames 이미 있는 항목 이름
 * @returns {{ name: string, goal?: number, unit?: string }[]}
 */
export function recommendAvailable(pool, existingNames, count = 3) {
  const have = new Set(existingNames);
  return pool.filter((p) => !have.has(p.name)).slice(0, count);
}

export const recommendChipLabel = (p) => (p.goal ? `${p.name} · ${p.goal}${p.unit ?? ""}` : p.name);

/** 추천 칩을 고르면 채울 폼 값: 이름, 체크 방식(목표가 있으면 횟수), 하루 목표 글자. */
export function recommendToForm(p) {
  return p.goal
    ? { name: p.name, type: "count", goalText: `${p.goal}${p.unit ?? ""}` }
    : { name: p.name, type: "check", goalText: "1" };
}

/**
 * 라우트 params(문자열)에서 항목 추가 화면의 처음 값을 읽는다. 이름이 없으면 null(빈 화면).
 * 추천 칩에서 넘어온 값(이름·체크 방식·목표)을 그대로 채운다. 모양이 이상하면 기본값을 쓴다.
 */
export function draftFromParams(params) {
  const name = typeof params?.name === "string" ? params.name.trim() : "";
  if (!name) return null;
  const type = params.type === "count" ? "count" : "check";
  const goalText = typeof params.goalText === "string" && params.goalText ? params.goalText : type === "count" ? "8" : "1";
  return { name, type, goalText };
}

/** 선택 표시 색: 바탕 #FEECBF(colors.surfaceStrong), 테두리 1px #F6D06B(avatarPalette[1]). 복숭아·갈색 선택 색은 쓰지 않는다. */
// 내 줄을 길게 누르면(ROW_MENU_HOLD_MS) 뜨는 작은 메뉴. 키 → 동작은 rowMenuAction 이 정한다.
export const ROW_MENU = [
  { key: "edit", label: "수정", icon: "pencil" },
  { key: "delete", label: "삭제", danger: true, icon: "trash" },
];

/** 메뉴 키 → 동작. 알 수 없는 키는 null(아무것도 하지 않는다). */
export function rowMenuAction(key) {
  if (key === "edit") return "edit";
  if (key === "delete") return "delete";
  return null;
}

export const SELECT_BG = colors.surfaceStrong;
export const SELECT_BORDER = avatarPalette[1].backgroundColor;

/** 응원 보내기 시트 머리 줄. "오늘 3/3 모두 챙기셨어요" 또는 "오늘 1/3 챙기셨어요". */
export function cheerSubtitle(done, total) {
  if (total > 0 && done === total) return `오늘 ${done}/${total} 모두 챙기셨어요`;
  return `오늘 ${done}/${total} 챙기셨어요`;
}

/**
 * 응원 목록을 날짜별로 묶는다. 최근 날짜가 먼저, 같은 날은 시각이 늦은 것이 먼저다.
 * @param {{ date: string, time: string }[]} list
 * @returns {{ date: string, label: string, items: object[] }[]}
 */
export function groupCheersByDate(list, today) {
  const sorted = [...list].sort((a, b) => `${b.date} ${b.time}`.localeCompare(`${a.date} ${a.time}`));
  const groups = [];
  for (const cheer of sorted) {
    let group = groups.find((g) => g.date === cheer.date);
    if (!group) {
      group = { date: cheer.date, label: dateGroupLabel(cheer.date, today), items: [] };
      groups.push(group);
    }
    group.items.push(cheer);
  }
  return groups;
}

/** 오늘 받은 응원(화면의 "받은 응원 N" 칩). */
export const receivedTodayOf = (list, today) => list.filter((c) => c.direction === "received" && c.date === today);

/** 온보딩에 나오는 기본 3개(처음부터 고른 상태 3개: 물 마시기·영양제 먹기·안부 전화) + 1개 + 추천 이름. */
const ONBOARD_BASE = [
  { name: "물 마시기", type: "count", goal: 8, unit: "잔", days: ALL_DAYS, shareWithFamily: true, preselected: true },
  { name: "영양제 먹기", type: "check", goal: 1, unit: "", days: ALL_DAYS, shareWithFamily: true, preselected: true },
  { name: "안부 전화", type: "check", goal: 1, unit: "", days: ALL_DAYS, shareWithFamily: false, preselected: true },
  { name: "알림장 확인", type: "check", goal: 1, unit: "", days: WEEKDAYS, shareWithFamily: true, preselected: false },
];

/**
 * 온보딩 목록(카드 6개 = 2열 × 3행). 기본 4개 뒤에 추천 이름 앞의 두 개를 붙인다.
 * 나머지 추천 후보는 항목 추가 화면의 추천 풀에 있다.
 * @returns {{ name: string, type: string, goal: number, unit: string, days: string[], shareWithFamily: boolean, preselected: boolean }[]}
 */
export function onboardingChoices(recommendedNames) {
  const extra = recommendedNames.slice(0, 2).map((name) => ({
    name,
    type: "check",
    goal: 1,
    unit: "",
    days: ALL_DAYS,
    shareWithFamily: true,
    preselected: false,
  }));
  return [...ONBOARD_BASE, ...extra].map((c) => ({ ...c, days: [...c.days] }));
}

/**
 * 온보딩에서 저장할 항목 목록: 고른 이름들 중 이미 있는 이름과 같은 이름(화면 안 중복 포함)은 빼고, 저장할 모양으로 바꾼다.
 * "직접 만들기" 전에 고른 것을 먼저 등록할 때와 "이대로 시작하기"에 같이 쓴다.
 * @param {ReturnType<typeof onboardingChoices>} choices
 * @param {string[]} selectedNames 고른 이름
 * @param {string[]} existingNames 이미 있는 항목 이름
 */
export function onboardingToSave(choices, selectedNames, existingNames) {
  const taken = new Set(existingNames);
  const out = [];
  for (const choice of choices) {
    if (!selectedNames.includes(choice.name) || taken.has(choice.name)) continue;
    taken.add(choice.name);
    out.push(onboardingItem(choice));
  }
  return out;
}

/** 고른 온보딩 항목을 저장할 모양으로(알림은 끈 채로). */
export function onboardingItem(choice) {
  return {
    name: choice.name,
    type: choice.type,
    goal: choice.goal,
    unit: choice.unit,
    days: [...choice.days],
    alarm: false,
    shareWithFamily: choice.shareWithFamily,
  };
}

/** "안부 전화" 항목(이름에 포함) 중 오늘 해당하는 것. 전화 뒤 완료로 체크할 때 쓴다. 없으면 null. */
export const CALL_ITEM_KEYWORD = "안부 전화";
export function findCallItem(items, dateKey) {
  return items.find((item) => item.name.includes(CALL_ITEM_KEYWORD) && isScheduledOn(item, dateKey)) ?? null;
}

/**
 * 가비 추천 이야깃거리(고정 규칙, AI 호출 없음). 그 가족의 오늘 항목(가족에게 보이는 것)으로 만든다.
 * 완료한 것을 최대 두 개 "…하셨어요 / …여쭤보세요" 형식으로 말하고, 완료한 것이 없으면 기록 없는 항목을 하나 짚는다.
 * @param {{ name: string, type: string, goal: number, unit: string, entry?: object }[]} rows
 * @returns {{ say: string, ask: string }[]}
 */
export function talkingPoints(rows) {
  const done = rows.filter((row) => isDone(row, row.entry));
  if (done.length) return done.slice(0, 2).map(pointFor);
  if (rows.length) {
    return [{ say: `${rows[0].name} 기록이 아직 없어요`, ask: "그 일은 잘 챙기고 계신지 여쭤보세요" }];
  }
  return [{ say: "오늘 기록이 아직 없어요", ask: "오늘 하루 어떻게 지내셨는지 여쭤보세요" }];
}

function pointFor(row) {
  const { name, entry } = row;
  if (name.includes("산책")) return { say: `오늘 ${name} 하셨어요`, ask: "어디로 다녀오셨는지 여쭤보세요" };
  if (name.endsWith(" 먹기")) {
    const base = name.slice(0, -3);
    const when = entry?.doneAt ? `${formatClock(entry.doneAt)}에 ` : "";
    return { say: `${when}${base} 드셨어요`, ask: "요즘 몸은 어떠신지 물어보세요" };
  }
  if (isCount(row)) return { say: `${name} 목표를 채우셨어요`, ask: "물은 잘 드시는지 여쭤보세요" };
  return { say: `오늘 ${name} 완료하셨어요`, ask: "오늘 하루 어떠셨는지 여쭤보세요" };
}

// ── 개발용 가상 가족 ─────────────────────────────────────────────

/** 개발용 가상 가족 구성원 5명(FAMILY_ITEMS_MOCK 과 짝. 탭이 넘치는 모습을 보려고 다섯 명이다). */
export const DEV_FAMILY = [
  { id: "mom", name: "엄마", hasAccount: false },
  { id: "dad", name: "아빠", hasAccount: false },
  { id: "son", name: "아들", hasAccount: false },
  { id: "daughter", name: "딸", hasAccount: false },
  { id: "gran", name: "할머니", hasAccount: false },
];

/** 나를 나타내는 id(mock.js 의 ME_ID 와 같은 값. mock.js 가 이 파일을 가져오므로 여기에 따로 둔다). */
const SELF_ID = "me";

/**
 * 개발용 가상 가족을 가족 목록에 덧붙일지 정하고 합친다. 같은 id 가 이미 있으면 중복으로 넣지 않는다.
 * 개발 빌드(isDev)이고 실제 가족이 한 명도 없을(나 말고 구성원이 없을) 때만 덧붙인다. 그 밖에는 실제 목록 그대로다.
 * 덧붙인 가상 구성원은 hasAccount 가 false 라서 화면이 서버 호출 없이 읽기 전용으로 그린다.
 * @param {{ id: string, name: string }[]} members 실제 가족 구성원(나 포함)
 * @param {boolean} [isDev=false] 개발 빌드 여부(__DEV__ 를 넘긴다)
 */
export function withDevFamily(members, isDev = false) {
  const hasRealFamily = members.some((m) => m.id !== SELF_ID);
  if (!isDev || hasRealFamily) return members;
  const have = new Set(members.map((m) => m.id));
  return [...members, ...DEV_FAMILY.filter((m) => !have.has(m.id))];
}

/**
 * 처음 열었을 때 온보딩을 띄울지. 서버에 습관이 하나도 없고 온보딩 완료 표시(settings.onboarded)가 거짓일 때만 띄운다.
 * @param {object[]} items 내 습관 전체
 * @param {boolean} onboarded 서버 온보딩 완료 표시
 */
export function needsOnboarding(items, onboarded) {
  return !onboarded && items.length === 0;
}

/** 지금 시각을 "HH:MM" 으로. */
export function nowClock(date = new Date()) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// ── 받은 응원 (메인 맨 위: 안 누른 카드 / 전부 누르면 한 줄 배너) ─────

/** 이름 뒤의 주격 조사: 받침이 있으면 "이", 없으면 "가". 한글이 아니면 "이". */
export function subjectParticle(name) {
  const ch = name.charCodeAt(name.length - 1);
  if (ch < 0xac00 || ch > 0xd7a3) return "이";
  return (ch - 0xac00) % 28 === 0 ? "가" : "이";
}

/** 카드 제목: "아들이 응원을 보냈어요", "아빠가 응원을 보냈어요". */
export function cheerCardTitle(name) {
  return `${name}${subjectParticle(name)} 응원을 보냈어요`;
}

/**
 * 오늘 안 누른 받은 응원(카드로 보여 줄 것): 고마워를 안 보냈고(thanked 없음), 카드를 닫지도 않은(closed 없음) 오늘 받은 응원.
 * 고마워와 닫기는 서버에 저장되므로 앱을 다시 켜도 같은 카드가 보인다(닫은 카드는 다시 열리지 않는다).
 */
export const pendingCheersOf = (list, today) => receivedTodayOf(list, today).filter((c) => !c.thanked && !c.closed);

/** 카드 아래 줄: "오늘 받은 응원 1 / 2"(카드로 남은 것 / 오늘 받은 전체). */
export function cheerCaption(list, today) {
  return `오늘 받은 응원 ${openCheersOf(list, today).length} / ${receivedTodayOf(list, today).length}`;
}

/** 메인 카드로 아직 보여 줄 응원. pendingCheersOf 와 같다. */
export const openCheersOf = (list, today) => pendingCheersOf(list, today);

/** 오늘 받은 응원을 모두 처리(고마워 또는 닫기)했는가. 이때 한 줄 배너를 보인다. 받은 것이 없으면 false. */
export function allCheersHandled(list, today) {
  return receivedTodayOf(list, today).length > 0 && openCheersOf(list, today).length === 0;
}

/**
 * 전부 고마워 처리했을 때의 한 줄 배너 문구: "오늘 받은 응원 2개 · 아들, 딸". 보낸 사람은 중복 없이 받은 순서대로.
 */
export function cheerBannerText(list, today) {
  const todays = receivedTodayOf(list, today);
  const names = [...new Set(todays.map((c) => c.fromName))];
  return `오늘 받은 응원 ${todays.length}개 · ${names.join(", ")}`;
}

/**
 * 점 표시 모드(내 줄을 길게 눌러 줄 왼쪽에 점 세 개가 뜬 상태)에서 화면을 눌렀을 때 할 일. 한 번에 모두 닫는다.
 * - 점 표시 모드가 아니면 아무것도 하지 않는다("none").
 * - 줄(행)·점·메뉴 카드 위를 누른 것이면 그대로 둔다("none").
 * - 그 밖의 곳이면 메뉴와 점을 모두 닫는다("hideAll").
 * @param {{ showDots: boolean, insideRow: boolean }} s
 * @returns {"none" | "hideAll"}
 */
export function shouldHideDotsOnTouch({ showDots, insideRow }) {
  if (!showDots || insideRow) return "none";
  return "hideAll";
}
