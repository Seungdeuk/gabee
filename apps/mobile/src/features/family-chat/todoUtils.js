// 공동 할 일 순수 함수 모음(화면과 분리해 시험한다). 할 일 제목·담당자 같은 가족 데이터는 어디에도 기록하지 않는다.
import { roomErrorMessage } from "./chatUtils";

export const TITLE_MAX = 120;
export const OPEN_PREVIEW_LIMIT = 200;

/** 기한 선택 칩: key 는 안정된 식별자, days 는 오늘부터 며칠 뒤인지(null 이면 기한 없음). */
export const DUE_CHIPS = [
  { key: "none", label: "기한 없음", days: null },
  { key: "today", label: "오늘", days: 0 },
  { key: "tomorrow", label: "내일", days: 1 },
  { key: "d3", label: "3일 뒤", days: 3 },
  { key: "w1", label: "1주일 뒤", days: 7 },
];

const pad = (n) => String(n).padStart(2, "0");

/**
 * 기기 시간대의 날짜를 YYYY-MM-DD 로.
 * @param {Date} d
 * @returns {string}
 */
export const dateKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/**
 * 기한 칩이 뜻하는 날짜. 기기 시간대의 오늘에서 days 일 뒤이고, 월말·연말은 Date 가 넘겨 준다.
 * @param {string} key DUE_CHIPS 의 key
 * @param {Date} [now]
 * @returns {string | null} YYYY-MM-DD, 기한 없음이거나 모르는 칩이면 null
 */
export function dueFromChip(key, now = new Date()) {
  const chip = DUE_CHIPS.find((c) => c.key === key);
  if (!chip || chip.days == null) return null;
  return dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + chip.days));
}

/**
 * 저장된 기한이 어느 칩과 같은지(수정 창에서 선택 표시용). 칩에 없는 날짜면 null.
 * @param {string | null | undefined} due
 * @param {Date} [now]
 * @returns {string | null} 칩 key
 */
export function chipForDue(due, now = new Date()) {
  if (!due) return "none";
  return DUE_CHIPS.find((c) => c.days != null && dueFromChip(c.key, now) === due)?.key ?? null;
}

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * YYYY-MM-DD 가 실제 있는 날짜인지 확인하고 연·월·일로 나눈다(2월 31일 같은 값은 null).
 * @param {unknown} value
 * @returns {{ y: number, m: number, d: number } | null}
 */
function parseDay(value) {
  const match = DATE_RE.exec(String(value ?? ""));
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const check = new Date(y, m - 1, d);
  if (check.getFullYear() !== y || check.getMonth() !== m - 1 || check.getDate() !== d) return null;
  return { y, m, d };
}

/**
 * 오늘로부터 기한까지 남은 날수(지났으면 음수). 시간대·서머타임 영향이 없게 UTC 날짜끼리 뺀다.
 * @param {string} due YYYY-MM-DD
 * @param {Date} [now]
 * @returns {number | null} 날짜가 올바르지 않으면 null
 */
export function daysUntil(due, now = new Date()) {
  const day = parseDay(due);
  if (!day) return null;
  const a = Date.UTC(day.y, day.m - 1, day.d);
  const b = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((a - b) / 86400000);
}

/**
 * 기한 라벨: 오늘/내일/M월 D일, 지난 기한은 "지남 · M월 D일" 이고 overdue 가 true. 기한이 없으면 null.
 * @param {string | null | undefined} due YYYY-MM-DD
 * @param {Date} [now]
 * @returns {{ text: string, overdue: boolean } | null}
 */
export function dueLabel(due, now = new Date()) {
  const day = parseDay(due);
  const diff = day ? daysUntil(due, now) : null;
  if (!day || diff == null) return null;
  const md = `${day.m}월 ${day.d}일`;
  if (diff < 0) return { text: `지남 · ${md}`, overdue: true };
  if (diff === 0) return { text: "오늘", overdue: false };
  if (diff === 1) return { text: "내일", overdue: false };
  return { text: md, overdue: false };
}

/**
 * 구성원 id 로 표시 이름(별명이 아니라 표시 이름 우선)을 찾는다. 없으면 빈 문자열.
 * @param {{ id: string, name: string }[] | null | undefined} members
 * @param {string | null | undefined} id
 * @returns {string}
 */
export const assigneeName = (members, id) => (id ? ((Array.isArray(members) ? members : []).find((m) => m.id === id)?.name ?? "") : "");

const byCreated = (a, b) => String(a.created_at ?? "").localeCompare(String(b.created_at ?? ""));

/**
 * 안 끝난 일 정렬: 기한 빠른 순(기한 없는 것은 뒤), 같으면 만든 순서.
 * @param {object[]} todos
 * @returns {object[]}
 */
export const sortOpen = (todos) =>
  [...todos].sort((a, b) => {
    if (a.due_date && b.due_date && a.due_date !== b.due_date) return a.due_date < b.due_date ? -1 : 1;
    if (!!a.due_date !== !!b.due_date) return a.due_date ? -1 : 1;
    return byCreated(a, b);
  });

/**
 * 끝난 일 정렬: 최근에 끝낸 순.
 * @param {object[]} todos
 * @returns {object[]}
 */
export const sortDone = (todos) => [...todos].sort((a, b) => String(b.done_at ?? "").localeCompare(String(a.done_at ?? "")));

/**
 * 할 일을 안 끝난 것/끝난 것으로 나눠 각각 정렬한다.
 * @param {object[] | null | undefined} todos
 * @returns {{ open: object[], done: object[] }}
 */
export function splitTodos(todos) {
  const list = Array.isArray(todos) ? todos : [];
  return { open: sortOpen(list.filter((t) => !t.done)), done: sortDone(list.filter((t) => t.done)) };
}

/**
 * 낙관적 갱신: 서버 응답을 기다리지 않고 화면에 먼저 반영할 새 할 일. 완료 표시는 지금 시각과 내 id 를 임시로 쓴다.
 * assignee_id·due_date 는 patch 에 있는 키만 바뀌고 null 이면 비운다.
 * @param {object} todo
 * @param {{ title?: string, assignee_id?: string | null, due_date?: string | null, done?: boolean }} patch
 * @param {string | null} [meId]
 * @param {Date} [now]
 * @returns {object}
 */
export function applyPatch(todo, patch, meId = null, now = new Date()) {
  const next = { ...todo };
  if ("title" in patch) next.title = patch.title;
  if ("assignee_id" in patch) next.assignee_id = patch.assignee_id ?? null;
  if ("due_date" in patch) next.due_date = patch.due_date ?? null;
  if ("done" in patch) {
    next.done = !!patch.done;
    next.done_at = patch.done ? now.toISOString() : null;
    next.done_by = patch.done ? meId : null;
  }
  return next;
}

/**
 * 목록에서 id 가 같은 항목을 바꾼다(없으면 그대로).
 * @param {object[]} list
 * @param {string} id
 * @param {object} next 새 항목
 * @returns {object[]}
 */
export const replaceTodo = (list, id, next) => list.map((t) => (t.id === id ? next : t));

/**
 * 목록에서 id 가 같은 항목을 뺀다.
 * @param {object[]} list
 * @param {string} id
 * @returns {object[]}
 */
export const removeTodo = (list, id) => list.filter((t) => t.id !== id);

/**
 * 제목을 서버 규칙(연속 공백을 하나로, 1~120자)에 맞게 다듬는다. 비면 빈 문자열.
 * @param {string} title
 * @returns {string}
 */
export const cleanTitle = (title) => String(title ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, TITLE_MAX);

/**
 * 제목 입력이 보낼 수 있는 상태인지.
 * @param {string} title
 * @returns {boolean}
 */
export const canSubmitTitle = (title) => cleanTitle(title).length > 0;

/**
 * 소통 탭 카드용 미리보기: 안 끝난 일 개수와 맨 앞 제목들.
 * @param {object[] | null | undefined} openTodos
 * @param {number} [take] 미리 보일 개수
 * @returns {{ count: number, titles: string[] }}
 */
export function openPreview(openTodos, take = 2) {
  const list = Array.isArray(openTodos) ? sortOpen(openTodos.filter((t) => !t.done)) : [];
  return { count: list.length, titles: list.slice(0, take).map((t) => t.title) };
}

/**
 * AI 할 일 후보를 POST /family-chat/todos 본문으로. 사용자가 후보를 보고 누른 뒤에만 쓴다.
 * 담당자는 후보의 assignee_name 이 구성원 이름 또는 표시 이름과 정확히 같고 그런 구성원이 한 명뿐일 때만 정하고, 아니면 null 이다(짐작하지 않는다).
 * 기한은 실제 있는 YYYY-MM-DD 일 때만 쓴다.
 * @param {{ title?: string, assignee_name?: string | null, due?: string | null } | null | undefined} candidate
 * @param {{ id: string, name?: string, display_name?: string | null }[] | null | undefined} members
 * @returns {{ title: string, assignee_id: string | null, due_date: string | null, source: "chat" } | null} 제목이 비면 null
 */
export function candidateToTodoBody(candidate, members) {
  const title = cleanTitle(candidate?.title);
  if (!title) return null;
  const wanted = String(candidate?.assignee_name ?? "").trim();
  const hits = wanted ? (Array.isArray(members) ? members : []).filter((m) => m.name === wanted || m.display_name === wanted) : [];
  const assignee = hits.length === 1 ? hits[0].id : null;
  const due = parseDay(candidate?.due) ? candidate.due : null;
  return { title, assignee_id: assignee, due_date: due, source: "chat" };
}

const BY_CODE = {
  invalid_member: "같은 가족 구성원만 담당자로 정할 수 있어요",
  invalid_title: "할 일 제목을 1자 이상 적어 주세요",
  empty_update: "바꿀 내용이 없어요",
  todo_limit: "할 일이 너무 많아요. 끝난 할 일을 정리해 주세요",
  not_allowed: "만든 사람이나 가족 관리자만 지울 수 있어요",
  not_found: "이미 지워졌거나 없는 할 일이에요. 새로고침해 주세요",
};

/**
 * 할 일 오류를 사용자 문장으로(제목 같은 내용은 넣지 않는다). 모르는 코드는 대화방 오류 문구를 따른다.
 * 단 invalid_member·not_found 는 1:1 대화 문구 대신 할 일에 맞는 문구를 쓴다.
 * @param {{ code?: string } | null | undefined} error
 * @returns {string}
 */
export const todoErrorMessage = (error) => BY_CODE[error?.code] ?? roomErrorMessage(error);

/**
 * 고치기 창에서 바꾼 항목만 PATCH 본문으로. 제목은 다듬은 값이 달라졌을 때만, 담당자는 id 가 달라졌을 때만(null 이면 비움),
 * 기한은 칩이 바뀌었을 때만 보낸다(dueKey "keep" 은 칩에 없는 기존 날짜를 그대로 두는 선택).
 * @param {{ title: string, assignee_id: string | null, due_date: string | null }} todo 지금 저장된 값
 * @param {{ title: string, assigneeId: string | null, dueKey: string }} edited 창에서 고른 값
 * @param {Date} [now]
 * @returns {{ title?: string, assignee_id?: string | null, due_date?: string | null }} 바꿀 게 없으면 빈 객체
 */
export function buildEditPatch(todo, edited, now = new Date()) {
  const patch = {};
  const title = cleanTitle(edited.title);
  if (title && title !== todo.title) patch.title = title;
  if ((edited.assigneeId ?? null) !== (todo.assignee_id ?? null)) patch.assignee_id = edited.assigneeId ?? null;
  if (edited.dueKey !== "keep") {
    const due = dueFromChip(edited.dueKey, now);
    if (due !== (todo.due_date ?? null)) patch.due_date = due;
  }
  return patch;
}

/**
 * 새로 받은 목록(안 끝난 일 + 선택적으로 끝난 일)을 현재 목록에 합친다. 요청 중에 바뀐 항목(protectedIds)은 현재 화면의 값을 우선하고,
 * 그 사이 지워진 항목은 되살리지 않는다. id 중복은 한 번만 남긴다.
 * @param {object[]} current 지금 화면의 목록
 * @param {object[]} fetched 서버에서 받은 목록
 * @param {Set<string>} protectedIds 요청 중에 낙관적으로 바뀌었거나 바뀌는 중인 id
 * @returns {object[]}
 */
export function mergeFetched(current, fetched, protectedIds) {
  const byId = new Map(current.map((t) => [t.id, t]));
  const out = [];
  const seen = new Set();
  for (const f of fetched) {
    if (seen.has(f.id)) continue;
    const item = protectedIds.has(f.id) ? byId.get(f.id) : f;
    if (item) {
      out.push(item);
      seen.add(f.id);
    }
  }
  for (const id of protectedIds) if (!seen.has(id) && byId.has(id)) out.push(byId.get(id));
  return out;
}

/**
 * "완료한 일"을 펼친 응답을 현재 목록에 합친다. 안 끝난 일은 그대로 두고, 현재 목록에 이미 있거나 요청 중에 바뀐 id 는 현재 값을 우선하며 중복은 없다.
 * @param {object[]} current 지금 화면의 목록
 * @param {object[]} fetchedDone 서버에서 받은 끝난 일
 * @param {Set<string>} protectedIds 요청 중에 바뀐 id
 * @returns {object[]}
 */
export function mergeDone(current, fetchedDone, protectedIds) {
  const kept = current.filter((t) => !t.done || protectedIds.has(t.id));
  const ids = new Set(kept.map((t) => t.id));
  const added = [];
  for (const f of fetchedDone) {
    if (ids.has(f.id) || protectedIds.has(f.id)) continue;
    ids.add(f.id);
    added.push(f);
  }
  return [...kept, ...added];
}
