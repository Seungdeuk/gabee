import { useEffect, useSyncExternalStore } from "react";

import { isApiConfigured } from "@/shared/api/client";

import { getMyGroup } from "../family-group/api";
import * as api from "./api";
import { buildFamily } from "./members";
import { createMockItems, members, topics } from "./mock";

// 여러 화면이 같은 목록을 보도록 한 곳에 둔다. 서버 주소가 있으면(EXPO_PUBLIC_API_URL) 서버의 내 일정을 읽고 쓰며,
// 화면에는 바로 반영한 뒤 서버가 실패하면 되돌린다. 주소가 없으면 예전처럼 메모리 mock 으로 동작한다.
const useServer = isApiConfigured();
let items = useServer ? [] : createMockItems();
let nextId = 100;
let family = null; // 서버 모드에서 가족 그룹을 읽은 뒤의 id 변환기
let loading = null;
const pendingCreate = new Map(); // 임시 id → 서버에 만드는 중인 일정의 서버 id(그동안 온 수정·삭제·체크는 그 뒤에 보낸다)
const aliases = new Map(); // 임시 id → 만들어진 서버 id
const listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

const warn = (what, error) => console.warn(`[schedule] ${what} 실패`, error?.message ?? error);

/** 서버의 가족·주제·일정을 한 번 읽어 온다(화면이 처음 열릴 때). 실패하면 다음에 다시 시도한다. */
function ensureLoaded() {
  if (!useServer || loading) return loading;
  loading = (async () => {
    const [group, serverTopics, events] = await Promise.all([getMyGroup(), api.listTopics(), api.listEvents()]);
    family = buildFamily(group);
    members.splice(0, members.length, ...family.members);
    topics.splice(0, topics.length, ...serverTopics.map(({ id, name, color }) => ({ id, name, color })));
    items = events.map((event) => api.toItem(event, family));
    emit();
  })().catch((error) => {
    warn("일정 불러오기", error);
    loading = null;
  });
  return loading;
}

/** 서버 요청 전에 가족 변환기가 준비될 때까지 기다린다. */
async function ready() {
  await ensureLoaded();
  if (!family) throw new Error("가족 정보를 아직 못 불러왔어요");
  return family;
}

/** 임시 id 로 만드는 중이면 서버 id 가 나올 때까지 기다린다. @returns {Promise<string>} */
async function serverId(id) {
  if (pendingCreate.has(id)) return pendingCreate.get(id);
  return aliases.get(id) ?? id;
}

/** @returns {import("./model").ScheduleItem[]} 전체 항목 (화면에서 날짜·필터로 거른다) */
export function useScheduleItems() {
  useEffect(() => {
    ensureLoaded();
  }, []);
  return useSyncExternalStore(subscribe, () => items);
}

/** 훅이 아닌 곳(채팅 답변 만들기)에서 지금 항목을 읽는다. @returns {import("./model").ScheduleItem[]} */
export function getScheduleItems() {
  return items;
}

/**
 * @param {string} id
 * @returns {import("./model").ScheduleItem | undefined}
 */
export function useScheduleItem(id) {
  return useScheduleItems().find((item) => item.id === id);
}

const replaceItem = (id, next) => {
  items = items.map((item) => (item.id === id ? next(item) : item));
  emit();
};

/** 서버 요청이 실패했을 때 화면 상태를 요청 전으로 되돌린다. */
const restore = (before) => {
  items = before;
  emit();
};

/**
 * @param {Omit<import("./model").ScheduleItem, "id" | "checked">} data
 * @returns {import("./model").ScheduleItem} 새로 만든 항목 (서버 모드에서는 임시 id 로 보이다가 서버 id 로 바뀐다)
 */
export function addItem(data) {
  nextId += 1;
  const item = {
    ...data,
    id: useServer ? `tmp-${nextId}` : String(nextId),
    checked: false,
  };
  items = [...items, item];
  emit();
  if (!useServer) return item;

  const creating = (async () => {
    const f = await ready();
    const created = await api.createEvent(api.toBody(item, f, { create: true }));
    aliases.set(item.id, created.id);
    replaceItem(item.id, () => ({
      ...api.toItem(created, f),
      sharedWith: item.sharedWith,
    }));
    return created.id;
  })();
  pendingCreate.set(item.id, creating);
  creating.then(
    () => pendingCreate.delete(item.id),
    (error) => {
      warn("일정 등록", error);
      pendingCreate.delete(item.id);
      items = items.filter((x) => x.id !== item.id);
      emit();
    },
  );
  return item;
}

/**
 * @param {string} id
 * @param {Partial<import("./model").ScheduleItem>} patch
 */
export function updateItem(id, patch) {
  const before = items;
  const current = items.find((item) => item.id === id);
  replaceItem(id, (item) => ({ ...item, ...patch }));
  if (!useServer || !current) return;
  (async () => {
    const f = await ready();
    const sid = await serverId(id);
    const body = api.toPatchBody(patch, current, f);
    if (Object.keys(body).length === 0) return;
    const saved = await api.updateEvent(sid, body);
    replaceItem(sid, (item) => ({
      ...api.toItem(saved, f),
      sharedWith: item.sharedWith,
    }));
  })().catch((error) => {
    warn("일정 수정", error);
    restore(before);
  });
}

/** @param {string} id */
export function removeItem(id) {
  const before = items;
  items = items.filter((item) => item.id !== id);
  emit();
  if (!useServer) return;
  serverId(id)
    .then(api.deleteEvent)
    .catch((error) => {
      warn("일정 삭제", error);
      restore(before);
    });
}

/** 약속은 확인, 할 일은 완료. 다시 누르면 해제. @param {string} id */
export function toggleChecked(id) {
  const before = items;
  const current = items.find((item) => item.id === id);
  replaceItem(id, (item) => ({ ...item, checked: !item.checked }));
  if (!useServer || !current) return;
  serverId(id)
    .then((sid) => api.setEventChecked(sid, !current.checked))
    .catch((error) => {
      warn("확인 표시", error);
      restore(before);
    });
}

/**
 * 이 일정을 누가 공유했는지, 누구에게 공유했는지(앱 가족 id). 서버 모드에서만 서버에 묻는다.
 * @param {string} id
 * @returns {Promise<{ sharedBy: string | null, sharedWith: string[] } | null>} 실패하거나 서버가 없으면 null
 */
export async function loadSharing(id) {
  if (!useServer) return null;
  try {
    const f = await ready();
    const sharing = await api.getSharing(await serverId(id));
    return {
      sharedBy: sharing.shared_by ? f.toApp(sharing.shared_by) : null,
      sharedWith: sharing.shared_with.map(f.toApp).filter(Boolean),
    };
  } catch (error) {
    warn("공유 정보 불러오기", error);
    return null;
  }
}
