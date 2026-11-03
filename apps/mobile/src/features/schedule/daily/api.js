import AsyncStorage from "@react-native-async-storage/async-storage";

import { FAMILY_ITEMS_MOCK, FAMILY_PHONE_MOCK, SEED_ENTRIES, SEED_ITEMS, seedCheers } from "./mock";

// 데일리 체크의 모든 저장·조회가 모인 자리. 지금은 이 폰(AsyncStorage)에만 저장하고, 가족 기록·전화번호는 mock 이다.
// 서버가 생기면 이 파일의 함수 본문만 서버 호출로 바꾸면 된다(화면은 여기 함수만 부른다).
// 키에 .v1 을 붙이고, 사용자 id(scope)별로 따로 둔다. 읽기·쓰기가 실패해도 화면은 계속 동작한다.

const keyOf = (name, scope) => `gabee.schedule.daily.${name}.v1.${scope}`;

// 쓰기는 한 줄로 세운다. 빠르게 여러 번 눌러도 읽고-고치고-쓰기가 서로 겹치지 않게 한다.
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

const makeId = () => `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

/** 한 번만 하는 표시(온보딩 완료 등). 못 읽으면 "아직 아님"으로 본다. */
async function readFlag(key) {
  try {
    return (await AsyncStorage.getItem(key)) === "1";
  } catch {
    return false;
  }
}

async function writeFlag(key) {
  try {
    await AsyncStorage.setItem(key, "1");
  } catch {
    // 못 쓰면 다음 번에 다시 묻는다
  }
}

const onboardedKey = (scope) => keyOf("onboarded", scope);
const devFamilyKey = (scope) => keyOf("devFamily", scope);

/** 개발용 가상 가족 모드가 켜져 있는가(예시 데이터를 채우면 켜진다). */
export function loadDevFamily(scope) {
  return readFlag(devFamilyKey(scope));
}

/**
 * 개발용 예시 데이터 채우기(편집 화면 하단, __DEV__ 에서만 보인다). 내 항목·오늘 기록·받은 응원을 시안 값으로 덮어쓰고 온보딩을 건너뛴 상태로 만든다.
 * 처음 열 때 자동으로 부르지 않는다.
 * @param {string} dateKey 오늘 날짜
 */
export function seedExamples(scope, dateKey) {
  return serial(async () => {
    await writeJson(
      keyOf("items", scope),
      SEED_ITEMS.map((item) => ({ ...item })),
    );
    await writeJson(keyOf("entries", scope), { [dateKey]: { ...SEED_ENTRIES } });
    await writeJson(keyOf("cheers", scope), seedCheers(dateKey));
    await writeFlag(onboardedKey(scope));
    await writeFlag(devFamilyKey(scope)); // 가상 엄마·아빠를 가족 목록에 덧붙인다(개발용)
  });
}

/** 온보딩을 마쳤거나 건너뛴 적이 있는가. */
export function loadOnboarded(scope) {
  return readFlag(onboardedKey(scope));
}

/**
 * 온보딩 마무리: 고른 항목을 만들고 완료 표시를 남긴다. 고른 게 없으면(건너뛰기) 항목 없이 완료만 남긴다.
 * @param {object[]} items buildItem 과 같은 모양(id 없음)
 */
export function finishOnboarding(scope, items) {
  return serial(async () => {
    const list = await readJson(keyOf("items", scope), []);
    const base = Array.isArray(list) ? list : [];
    const added = items.map((item) => ({ ...item, id: makeId() }));
    await writeJson(keyOf("items", scope), [...base, ...added]);
    await writeFlag(onboardedKey(scope));
  });
}

/** 내 항목 전체(순서 포함). @returns {Promise<object[]>} */
export async function listItems(scope) {
  const list = await readJson(keyOf("items", scope), []);
  return Array.isArray(list) ? list : [];
}

/** 항목 한 개를 저장한다(id 가 있으면 고치고, 없으면 새 id 를 붙여 맨 뒤에 넣는다). @returns {Promise<object>} 저장된 항목 */
export function saveItem(scope, item) {
  return serial(async () => {
    const list = await listItems(scope);
    const saved = item.id ? { ...item } : { ...item, id: makeId() };
    const exists = list.some((x) => x.id === saved.id);
    const next = exists ? list.map((x) => (x.id === saved.id ? saved : x)) : [...list, saved];
    await writeJson(keyOf("items", scope), next);
    return saved;
  });
}

/** 항목 전체 목록을 한 번에 바꾼다(순서 바꾸기에 쓴다). */
export function replaceItems(scope, items) {
  return serial(() => writeJson(keyOf("items", scope), items));
}

/** 항목을 지운다. 그날의 기록은 그대로 둔다. */
export function deleteItem(scope, id) {
  return serial(async () => {
    const list = await listItems(scope);
    await writeJson(
      keyOf("items", scope),
      list.filter((x) => x.id !== id),
    );
  });
}

/** 날짜의 기록 전체. @returns {Promise<Record<string, { done?: boolean, count?: number, doneAt?: string | null }>>} 항목 id → 기록 */
export async function listEntries(scope, dateKey) {
  const all = await readJson(keyOf("entries", scope), {});
  return (all && all[dateKey]) || {};
}

/** 날짜 하나의 항목 기록을 저장한다. */
export function setEntry(scope, dateKey, itemId, entry) {
  return serial(async () => {
    const all = await readJson(keyOf("entries", scope), {});
    const base = all && typeof all === "object" ? all : {};
    const day = { ...(base[dateKey] || {}), [itemId]: entry };
    await writeJson(keyOf("entries", scope), { ...base, [dateKey]: day });
    return entry;
  });
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
 * 가족 구성원 한 사람의 항목(오늘 기록 포함). 지금은 mock 이다. 가족에게 보이기 필터는 호출한 쪽(logic.familyRowsOf)이 한다.
 * @returns {Promise<object[]>}
 */
export async function listFamilyToday(memberId) {
  return (FAMILY_ITEMS_MOCK[memberId] ?? []).map((item) => ({ ...item }));
}

/**
 * 개발용 초기화: 이 사용자(scope)의 데일리 체크 저장값을 모두 지운다(항목·기록·탭 순서·온보딩·응원·통화 메모·시드·가상 가족 플래그).
 * 다음에 메인을 열면 온보딩이 뜬다. 다른 사용자의 값은 건드리지 않는다.
 */
export async function resetAll(scope) {
  const names = ["items", "entries", "tabs", "onboarded", "cheers", "callMemo", "devFamily", "seeded"];
  try {
    await AsyncStorage.multiRemove(names.map((name) => keyOf(name, scope)));
  } catch {
    // 지우지 못해도 화면은 계속 동작한다(다음에 다시 시도)
  }
}

/** 가족 구성원 전화번호 mock. @returns {Promise<{ masked: string, dial: string } | null>} */
export async function listFamilyPhone(memberId) {
  return FAMILY_PHONE_MOCK[memberId] ?? null;
}

// ── 응원 ──
// 서버 자리: 보내기는 POST(상대 폰으로 알림), 받기는 GET(가족 응원 목록), 고마워는 PATCH 로 바꾼다.
// 지금은 이 폰에만 저장한다. 상대 폰으로 가는 전송과 가족 대화방(도란도란) 연동은 서버가 생긴 뒤의 일이다.

const cheersKey = (scope) => keyOf("cheers", scope);

/** 받은·보낸 응원 전체. @returns {Promise<object[]>} */
export async function listCheers(scope) {
  const list = await readJson(cheersKey(scope), []);
  return Array.isArray(list) ? list : [];
}

/**
 * 응원을 보낸다(이 폰에만 기록). cheer: { toName, toId, kind, text, date, time, groupChat }
 * groupChat 은 "가족 대화방에도 남기기" 표시 값이다. 실제 채팅 전송은 하지 않는다.
 */
export function sendCheer(scope, cheer) {
  return serial(async () => {
    const list = await listCheers(scope);
    const saved = { ...cheer, id: makeId(), direction: "sent", fromName: "나" };
    await writeJson(cheersKey(scope), [...list, saved]);
    return saved;
  });
}

/** 받은 응원의 "고마워" 표시를 켜거나 끈다. 상대에게 알리지는 않는다(서버 연결 뒤). */
export function toggleCheerThanked(scope, id) {
  return serial(async () => {
    const list = await listCheers(scope);
    await writeJson(
      cheersKey(scope),
      list.map((c) => (c.id === id ? { ...c, thanked: !c.thanked } : c)),
    );
  });
}

// ── 전화 ──
// 통화 메모는 나만 보는 값이라 서버에 보내지 않는다(연결 뒤에도 로컬 전용).

/** 날짜·가족 구성원별 통화 메모. @returns {Promise<string>} */
export async function loadCallMemo(scope, dateKey, memberId) {
  const all = await readJson(keyOf("callMemo", scope), {});
  const text = all?.[dateKey]?.[memberId];
  return typeof text === "string" ? text : "";
}

export function saveCallMemo(scope, dateKey, memberId, text) {
  return serial(async () => {
    const all = await readJson(keyOf("callMemo", scope), {});
    const base = all && typeof all === "object" ? all : {};
    const day = { ...(base[dateKey] || {}), [memberId]: text };
    await writeJson(keyOf("callMemo", scope), { ...base, [dateKey]: day });
  });
}
