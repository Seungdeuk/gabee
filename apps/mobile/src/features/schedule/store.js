import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useSyncExternalStore } from "react";

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

// 가족·주제는 배열을 제자리에서 바꾸는 값(다른 화면이 mock 의 배열을 직접 읽는다)이다. 화면이 다시 그려지게 하려면 구독하는 값의
// 모양이 바뀌어야 하므로, 바뀔 때마다 사본(스냅샷)을 새로 만들어 둔다. 훅에서 매번 slice() 하면 React Compiler 가 결과를
// 캐시해 지우거나 만들어도 화면이 그대로일 수 있다(다른 화면에 다녀와야 반영됨).
let topicsSnapshot = topics.slice();
let membersSnapshot = members.slice();
const emit = () => {
  topicsSnapshot = topics.slice();
  membersSnapshot = members.slice();
  listeners.forEach((fn) => fn());
};
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

let refreshing = null;

/**
 * 서버의 내 일정을 다시 읽어 목록을 새로 채운다. 채팅(AI 비서)이나 다른 기기에서 서버에 만든 일정이 이 목록에 없어서 생기는
 * 누락을 막는다: 일정 화면이 다시 보일 때 부른다. 처음 읽기 전이거나, 다시 읽는 중이거나, 서버에 만드는 중인 일정이 있으면
 * (그 임시 항목이 사라지지 않게) 아무것도 하지 않는다.
 * @returns {Promise<void> | null}
 */
export function refreshItems() {
  if (!useServer || !family || refreshing || pendingCreate.size > 0) return refreshing;
  refreshing = api
    .listEvents()
    .then((events) => {
      if (pendingCreate.size > 0) return; // 읽는 사이 새로 만든 일정이 있으면 그 항목을 지우지 않는다
      items = events.map((event) => api.toItem(event, family));
      emit();
    })
    .catch((error) => warn("일정 새로고침", error))
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** 서버 요청 전에 가족 변환기가 준비될 때까지 기다린다. */
export async function ready() {
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
  useFocusEffect(
    useCallback(() => {
      refreshItems(); // 다른 탭(AI 비서 채팅 등)에서 만든 일정이 이 화면으로 돌아올 때 보이게 한다
    }, []),
  );
  return useSyncExternalStore(subscribe, () => items);
}

/** 주제 목록. 추가·삭제·서버 로드 때 새 스냅샷이 만들어져 화면이 바로 다시 그려진다. */
export function useTopics() {
  useEffect(() => {
    ensureLoaded();
  }, []);
  return useSyncExternalStore(subscribe, () => topicsSnapshot);
}

/**
 * 가족 구성원(나 포함). 서버에서 가족을 읽은 뒤에 채워지므로 화면이 모듈 로드 때가 아니라 그릴 때마다 이 훅으로 읽는다.
 * 가족이 바뀔 때 새 스냅샷이 만들어져 화면이 바로 다시 그려진다.
 * @returns {import("./model").Member[]}
 */
export function useMembers() {
  useEffect(() => {
    ensureLoaded();
  }, []);
  return useSyncExternalStore(subscribe, () => membersSnapshot);
}

/** 내 사용자 id(서버에서 가족을 읽은 뒤). 서버가 없거나 아직 못 읽었으면 빈 글자. 폰에만 저장하는 값의 키에 쓴다. */
export function useMeUserId() {
  return useSyncExternalStore(subscribe, () => family?.meUserId ?? "");
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
 * 주제를 만든다. 서버 모드에서는 서버가 정한 id 를 쓰고, 실패하면(같은 이름 409 등) 던진다. 서버가 없으면 메모리에만 추가한다.
 * @param {string} name
 * @param {string} color TOPIC_TEXT 의 키
 * @returns {Promise<{ id: string, name: string, color: string }>}
 */
export async function addTopic(name, color) {
  let topic;
  if (useServer) {
    const { id, name: saved, color: savedColor } = await api.createTopic(name, color);
    topic = { id, name: saved, color: savedColor };
  } else {
    nextId += 1;
    topic = { id: `topic-${nextId}`, name, color };
  }
  topics.push(topic);
  emit();
  return topic;
}

/** 주제를 지운다. 그 주제를 붙였던 일정은 주제 없음이 된다. 서버가 실패하면 되돌린다. @param {string} id */
export function removeTopic(id) {
  const index = topics.findIndex((t) => t.id === id);
  if (index < 0) return;
  const [removed] = topics.splice(index, 1);
  const before = items;
  items = items.map((item) => (item.topicId === id ? { ...item, topicId: null } : item));
  emit();
  if (!useServer) return;
  api.deleteTopic(id).catch((error) => {
    warn("주제 삭제", error);
    if (!topics.some((t) => t.id === id)) topics.splice(Math.min(index, topics.length), 0, removed);
    // 그동안 바뀐 다른 일정은 두고, 이 주제였던 항목만 되돌린다.
    const had = new Set(before.filter((item) => item.topicId === id).map((item) => item.id));
    items = items.map((item) => (had.has(item.id) ? { ...item, topicId: id } : item));
    emit();
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

/** 에이전트가 서버에서 일정을 바꿨을 때 내 일정을 다시 읽는다(서버 모드에서만). */
export async function reloadItems() {
  if (!useServer) return;
  try {
    const f = await ready();
    items = (await api.listEvents()).map((event) => api.toItem(event, f));
    emit();
  } catch (error) {
    warn("일정 다시 읽기", error);
  }
}
