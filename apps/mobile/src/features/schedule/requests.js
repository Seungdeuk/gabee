import { useSyncExternalStore } from "react";

import { createMockRequests } from "./mock";

// 서버 연동 전까지 쓰는 메모리 저장소. 같이(요청) 목록을 여러 화면이 같이 본다.
let requests = createMockRequests();
let nextId = 100;
const listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** @returns {import("./model").TogetherRequest[]} 전체 요청(보낸 것·받은 것) */
export function useRequests() {
  return useSyncExternalStore(subscribe, () => requests);
}

/**
 * @param {string} id
 * @returns {import("./model").TogetherRequest | undefined}
 */
export function useRequest(id) {
  return useRequests().find((request) => request.id === id);
}

/**
 * 같이를 보낸다. 답은 아직 없고 취소되지 않은 상태로 시작한다.
 * @param {Omit<import("./model").TogetherRequest, "id" | "replies" | "cancelled">} data
 * @returns {import("./model").TogetherRequest}
 */
export function sendRequest(data) {
  nextId += 1;
  const request = { ...data, id: `q${nextId}`, replies: {}, cancelled: false };
  requests = [request, ...requests];
  emit();
  return request;
}

/** 답을 기다리는 동안 보낸 사람이 보내기를 취소한다. @param {string} id */
export function cancelRequest(id) {
  requests = requests.map((request) => (request.id === id ? { ...request, cancelled: true } : request));
  emit();
}
