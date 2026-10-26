import { useSyncExternalStore } from "react";

import { createMockItems } from "./mock";

// 서버 연동 전까지 쓰는 메모리 저장소. 여러 화면이 같은 목록을 보도록 한 곳에 둔다.
// 서버가 붙으면 이 파일의 함수 본문만 api.js 호출로 바꾸고 화면은 그대로 둔다.
let items = createMockItems();
let nextId = 100;
const listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** @returns {import("./model").ScheduleItem[]} 전체 항목 (화면에서 날짜·필터로 거른다) */
export function useScheduleItems() {
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

/**
 * @param {Omit<import("./model").ScheduleItem, "id" | "checked">} data
 * @returns {import("./model").ScheduleItem} 새로 만든 항목
 */
export function addItem(data) {
  nextId += 1;
  const item = { ...data, id: String(nextId), checked: false };
  items = [...items, item];
  emit();
  return item;
}

/**
 * @param {string} id
 * @param {Partial<import("./model").ScheduleItem>} patch
 */
export function updateItem(id, patch) {
  items = items.map((item) => (item.id === id ? { ...item, ...patch } : item));
  emit();
}

/** @param {string} id */
export function removeItem(id) {
  items = items.filter((item) => item.id !== id);
  emit();
}

/** 약속은 확인, 할 일은 완료. 다시 누르면 해제. @param {string} id */
export function toggleChecked(id) {
  items = items.map((item) => (item.id === id ? { ...item, checked: !item.checked } : item));
  emit();
}
