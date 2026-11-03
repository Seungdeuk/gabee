import AsyncStorage from "@react-native-async-storage/async-storage";

import { apiFetch } from "@/shared/api/client";

import { ready } from "../store";

import { DEV_SAMPLE_ITEMS } from "./mock";
import {
  CHEER_KIND_TO_SERVER,
  cheerFromServer,
  entryToServer,
  itemFromServer,
  itemToServer,
  memberItemFromServer,
  summaryFromServer,
} from "./serverMap";

// 데일리 체크의 모든 저장·조회가 모인 자리. 습관·기록·응원·온보딩 표시는 서버(/schedule/check/*)에 둔다.
// 폰(AsyncStorage)에는 가족 탭 순서·숨김만 남긴다(키에 내 사용자 id). 화면은 이 파일의 함수만 부른다.
// 가족 id 는 앱 규칙(나 "me", 엄마·아빠 "mom"·"dad", 나머지 서버 사용자 id)이고, 바꾸는 일은 store 의 ready() 가 준 변환기로 한다.

const BASE = "/schedule/check";
const keyOf = (name, scope) => `gabee.schedule.daily.${name}.v1.${scope}`;
const seg = (value) => encodeURIComponent(String(value));

// ── 폰에 남기는 것: 가족 탭 순서와 숨김 ──

let queue = Promise.resolve();
function serial(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => {});
  return run;
}

async function readJson(key, fallback) {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (raw == null) return fallback;
    return JSON.parse(raw) ?? fallback;
  } catch {
    return fallback;
  }
}

async function writeJson(key, value) {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 저장이 안 돼도 이번 화면에서는 계속 쓸 수 있다
  }
}

/** 가족 탭 순서와 숨긴 탭. @returns {Promise<{ order: string[], hidden: string[] }>} */
export async function loadTabOrder(scope) {
  const tabs = await readJson(keyOf("tabs", scope), null);
  return {
    order: Array.isArray(tabs?.order) ? tabs.order : [],
    hidden: Array.isArray(tabs?.hidden) ? tabs.hidden : [],
  };
}

/** 가족 탭 순서와 숨긴 탭을 저장한다. */
export function saveTabOrder(scope, tabs) {
  return serial(() => writeJson(keyOf("tabs", scope), { order: tabs.order, hidden: tabs.hidden }));
}

/**
 * 지난 버전이 폰에 남긴 습관·기록·응원·온보딩 값을 지운다(서버로 옮기지 않고 버린다). 여러 번 불러도 괜찮다.
 */
export async function dropLocalCopy(scope) {
  const names = ["items", "entries", "onboarded", "cheers", "devFamily", "seeded"];
  try {
    await AsyncStorage.multiRemove(names.map((name) => keyOf(name, scope)));
  } catch {
    // 지우지 못해도 화면은 서버 값으로 동작한다
  }
}

// ── 내 습관 ──

/** 내 습관 전체(순서대로, 요일과 상관없이). @returns {Promise<object[]>} */
export async function listItems() {
  return (await apiFetch(`${BASE}/items`)).map(itemFromServer);
}

/**
 * 습관 한 개를 저장한다. id 가 있으면 고치고(PUT), 없으면 새로 만든다(POST, 맨 뒤에 붙는다).
 * @param {object} item buildItem 의 결과(id 는 있을 수도 없을 수도 있다)
 * @returns {Promise<object>} 서버가 준 항목(화면 모양)
 */
export async function saveItem(item) {
  const body = itemToServer(item);
  const row = item.id
    ? await apiFetch(`${BASE}/items/${seg(item.id)}`, { method: "PUT", body })
    : await apiFetch(`${BASE}/items`, { method: "POST", body });
  return itemFromServer(row);
}

/** 습관을 지운다(행을 지운다). 오늘 기록도 함께 없어진다. */
export function deleteItem(id) {
  return apiFetch(`${BASE}/items/${seg(id)}`, { method: "DELETE" });
}

/**
 * 내 습관 전체의 새 순서를 한 번에 저장한다(누락·중복이 있으면 서버가 400).
 * @param {object[]} items 원하는 순서의 전체 목록
 * @returns {Promise<object[]>} 서버가 정리한 목록
 */
export async function replaceItems(items) {
  const rows = await apiFetch(`${BASE}/items/order`, { method: "PUT", body: { ids: items.map((x) => x.id) } });
  return rows.map(itemFromServer);
}

/**
 * 오늘 기록을 저장한다. 한 번 체크는 done, 횟수는 count(절대값)를 보낸다. 서버의 항목(오늘 기록 포함)을 돌려준다.
 * @param {object} item 항목(id·type)
 * @param {object} entry 바꾼 뒤의 기록
 * @returns {Promise<object>} 서버가 준 항목(entry 포함)
 */
export async function setEntry(item, entry) {
  const row = await apiFetch(`${BASE}/items/${seg(item.id)}/entry`, { method: "PUT", body: entryToServer(item, entry) });
  return itemFromServer(row);
}

// ── 온보딩 · 설정 ──

/** 온보딩을 마쳤거나 건너뛴 적이 있는가(서버 설정). */
export async function loadOnboarded() {
  return Boolean((await apiFetch(`${BASE}/settings`)).onboarded);
}

/** 온보딩 완료 표시를 바꾼다. */
export function setOnboarded(onboarded) {
  return apiFetch(`${BASE}/settings`, { method: "PUT", body: { onboarded } });
}

/**
 * 온보딩 마무리: 고른 습관을 차례로 만들고 완료 표시를 남긴다. 고른 게 없으면(건너뛰기) 완료 표시만 남긴다.
 * @param {object[]} items onboardingToSave 의 결과(id 없음)
 */
export async function finishOnboarding(items) {
  for (const item of items) {
    await saveItem(item); // 순서대로 만들어야 목록 순서가 고른 순서를 따른다
  }
  await setOnboarded(true);
}

// ── 가족 ──

/** 가족 구성원 요약(나 포함): 앱 id → { done, total }. 탭 라벨에 쓴다. @returns {Promise<object[]>} */
export async function listFamilySummary() {
  const fam = await ready();
  const rows = await apiFetch(`${BASE}/members/summary`);
  return rows.map((row) => summaryFromServer(row, fam.toApp));
}

/**
 * 가족 한 사람의 오늘 습관(가족에게 보이는 것, 오늘 요일). 앱 id 로 부른다.
 * @param {string} appId "mom" 같은 앱 id
 * @returns {Promise<object[]>}
 */
export async function listFamilyToday(appId) {
  const fam = await ready();
  const userId = fam.toUser(appId);
  if (!userId) throw new Error("가족 구성원을 찾지 못했어요");
  const body = await apiFetch(`${BASE}/members/${seg(userId)}/today`);
  return body.items.map(memberItemFromServer);
}

// ── 응원 ──

/**
 * 받은 또는 보낸 응원 목록(최근 것이 앞에 온다는 보장은 없다. 화면이 날짜별로 묶는다).
 * @param {"received" | "sent"} direction
 * @returns {Promise<object[]>}
 */
export async function listCheers(direction = "received") {
  const rows = await apiFetch(`${BASE}/cheers?direction=${direction}`);
  return rows.map((row) => cheerFromServer(row, direction));
}

/**
 * 응원을 보낸다. 받는 사람은 앱 id(가족 구성원)로 고른다. 가족 대화방 남기기는 chat_left 로 저장만 한다.
 * @param {{ toId: string, kind: "love" | "best" | "well", text: string, groupChat: boolean }} cheer
 */
export async function sendCheer({ toId, kind, text, groupChat }) {
  const fam = await ready();
  const toUserId = fam.toUser(toId);
  if (!toUserId) throw new Error("가족 구성원을 찾지 못했어요");
  const row = await apiFetch(`${BASE}/cheers`, {
    method: "POST",
    body: { to_user_id: toUserId, kind: CHEER_KIND_TO_SERVER[kind], message: text, chat_left: Boolean(groupChat) },
  });
  return cheerFromServer(row, "sent");
}

/** 받은 응원에 "고마워"를 보낸다(본문 없음, 처음 한 번만 남고 되돌림은 없다). */
export async function markCheerThanked(id) {
  return cheerFromServer(await apiFetch(`${BASE}/cheers/${seg(id)}/thanked`, { method: "PUT" }), "received");
}

/** 받은 응원 카드를 닫는다(본문 없음, 되돌림 없음). */
export async function markCheerClosed(id) {
  return cheerFromServer(await apiFetch(`${BASE}/cheers/${seg(id)}/closed`, { method: "PUT" }), "received");
}

// ── 개발용 도구(__DEV__ 에서만 화면에 보인다) ──

/**
 * 개발용 예시 습관 채우기: 이름이 없는 예시 습관을 만들고 완료 표시를 남긴다.
 * @param {string[]} existingNames 이미 있는 습관 이름(중복을 막는다)
 */
export async function seedExamples(existingNames) {
  const have = new Set(existingNames);
  for (const sample of DEV_SAMPLE_ITEMS) {
    if (have.has(sample.name)) continue;
    await saveItem(sample);
  }
  await setOnboarded(true);
}

/**
 * 개발용 초기화: 내 습관을 모두 지우고 온보딩 완료 표시를 끈다(다음에 메인을 열면 온보딩). 받은 응원은 서버에서 지울 수 없어 그대로 둔다.
 * 가족 탭 순서도 이 폰에서 지운다.
 */
export async function resetAll(scope) {
  const rows = await listItems();
  for (const row of rows) {
    await deleteItem(row.id);
  }
  await setOnboarded(false);
  try {
    await AsyncStorage.removeItem(keyOf("tabs", scope));
  } catch {
    // 지우지 못해도 다음 화면에서 다시 정한다
  }
}
