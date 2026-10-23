import { useSyncExternalStore } from "react";

import { KIND } from "./constants";
import { createMockRequests, ME_ID } from "./mock";
import { addItem, removeItem } from "./store";
import { todayKey } from "./utils/date";

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

/**
 * 내가 아직 답하지 않은 받은 같이의 개수(날짜가 안 지난 것만, 보낸 사람이 취소한 것 제외). 메인의 "주고 받은" 숫자 배지에 쓴다.
 * @returns {number}
 */
export function useNewReceivedCount() {
  const today = todayKey();
  return useRequests().filter((r) => isReceived(r) && !r.cancelled && !r.replies[ME_ID] && r.date >= today).length;
}

const isReceived = (request) => request.fromId !== ME_ID && request.toIds.includes(ME_ID);

// 내 답을 정하거나 바꾼다. 수락해서 만든 내 일정의 id 도 같이 적어 두어, 답을 바꾸면 그 일정을 지울 수 있게 한다.
const setReply = (id, answer, itemId = null) => {
  requests = requests.map((request) =>
    request.id === id ? { ...request, replies: { ...request.replies, [ME_ID]: answer }, itemId } : request,
  );
  emit();
};

/**
 * 답을 바꿀 수 있는 같이인지. 보낸 사람이 취소하지 않았고, 아직 날짜가 안 지났다.
 * @param {import("./model").TogetherRequest} request
 * @returns {boolean}
 */
export const canAnswer = (request) => !request.cancelled && request.date >= todayKey();

/**
 * 받은 같이를 수락한다. 부탁에 적힌 날짜·시간·장소·메모 그대로 내 약속 또는 할 일로 들어가고, 보낸 사람과 공유된다.
 * 이름표는 보낸 사람이 정한 "누구"다. 날짜가 지나기 전에는 다시 수락해 약속↔할 일을 바꿀 수 있고, 그러면 이전에 만든 일정은 지워진다.
 * @param {string} id
 * @param {"appointment" | "todo"} kind 내 일정에 넣는 형태
 */
export function acceptRequest(id, kind) {
  const request = requests.find((r) => r.id === id);
  if (!request || request.cancelled) return;
  if (request.replies[ME_ID] && !canAnswer(request)) return;
  if (request.itemId) removeItem(request.itemId);
  const item = addItem({
    kind,
    title: request.title,
    date: request.date,
    // 종일은 약속에만 있다. 할 일로 넣으면 시간 없이 그날의 할 일이 된다.
    allDay: kind === KIND.appointment && request.allDay,
    startTime: request.allDay ? null : request.startTime,
    endTime: request.allDay ? null : request.endTime,
    place: request.place,
    memo: request.memo,
    whoIds: request.whoIds,
    topicId: null,
    sharedWith: [request.fromId],
    createdBy: ME_ID,
  });
  setReply(id, "accepted", item.id);
}

/**
 * 받은 같이를 어렵다고 답한다. 보낸 사람에게는 알리지 않는다. 먼저 수락했던 것이면(날짜가 지나기 전) 그때 만든 내 일정을 지운다.
 * @param {string} id
 */
export function declineRequest(id) {
  const request = requests.find((r) => r.id === id);
  if (!request || request.cancelled) return;
  if (request.replies[ME_ID] && !canAnswer(request)) return;
  if (request.itemId) removeItem(request.itemId);
  setReply(id, "declined");
}
