import { useEffect, useSyncExternalStore } from "react";

import { isApiConfigured } from "@/shared/api/client";

import * as api from "./api";
import { KIND } from "./constants";
import { createMockRequests, ME_ID } from "./mock";
import { addItem, ready, reloadItems, removeItem } from "./store";
import { toRequest, toRequestBody } from "./together_convert";
import { todayKey } from "./utils/date";

// 같이(요청) 목록을 여러 화면이 같이 보는 저장소. 서버 주소가 있으면(EXPO_PUBLIC_API_URL) 서버의 보낸·받은 목록을 읽고 쓰며,
// 화면에는 바로 반영한 뒤 서버가 실패하면 되돌린다. 주소가 없으면 예전처럼 메모리 mock 으로 동작한다.
const useServer = isApiConfigured();
let requests = useServer ? [] : createMockRequests();
let nextId = 100;
let loading = null;
const pendingCreate = new Map(); // 임시 id → 서버에 만드는 중인 요청의 서버 id(그동안 온 취소·답은 그 뒤에 보낸다)
const aliases = new Map(); // 임시 id → 만들어진 서버 id
const listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

const warn = (what, error) => console.warn(`[schedule] ${what} 실패`, error?.message ?? error);

/** 서버 모드에서 가족 정보가 준비된 뒤 요청 목록을 한 번 읽는다. 실패하면 다음에 다시 시도한다. */
function ensureLoaded() {
  if (!useServer || loading) return;
  loading = (async () => {
    const f = await ready();
    requests = (await api.listRequests()).map((r) => toRequest(r, f));
    emit();
  })().catch((error) => {
    warn("같이 불러오기", error);
    loading = null;
  });
}

/** 임시 id 로 만드는 중이면 서버 id 가 나올 때까지 기다린다. @returns {Promise<string>} */
async function serverId(id) {
  if (pendingCreate.has(id)) return pendingCreate.get(id);
  return aliases.get(id) ?? id;
}

const replaceRequest = (id, next) => {
  requests = requests.map((request) => (request.id === id ? next(request) : request));
  emit();
};

/** 서버 요청이 실패했을 때 화면 상태를 요청 전으로 되돌린다. */
const restore = (before) => {
  requests = before;
  emit();
};

/** @returns {import("./model").TogetherRequest[]} 전체 요청(보낸 것·받은 것) */
export function useRequests() {
  useEffect(() => {
    ensureLoaded();
  }, []);
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
  const request = { ...data, id: useServer ? `tmp-${nextId}` : `q${nextId}`, replies: {}, cancelled: false };
  requests = [request, ...requests];
  emit();
  if (!useServer) return request;

  // 서버 모드: 서버 응답으로 바꾸고, 실패하면 목록에서 뺀다. 서버는 "누구"를 저장하지 않으므로 whoIds 는 비운다.
  const creating = (async () => {
    const f = await ready();
    const created = await api.createRequest(toRequestBody(request, f));
    aliases.set(request.id, created.id);
    replaceRequest(request.id, () => toRequest(created, f));
    return created.id;
  })();
  pendingCreate.set(request.id, creating);
  creating.then(
    () => pendingCreate.delete(request.id),
    (error) => {
      warn("같이 보내기", error);
      pendingCreate.delete(request.id);
      requests = requests.filter((r) => r.id !== request.id);
      emit();
    },
  );
  return request;
}

/** 서버 모드에서 요청을 서버에 보내고 응답으로 갱신한다. 실패하면 before 로 되돌린다. */
function sync(id, before, what, call) {
  return (async () => {
    const f = await ready();
    const saved = await call(await serverId(id));
    replaceRequest(await serverId(id), () => toRequest(saved, f));
  })().catch((error) => {
    warn(what, error);
    restore(before);
  });
}

/** 답을 기다리는 동안 보낸 사람이 보내기를 취소한다. @param {string} id */
export function cancelRequest(id) {
  const before = requests;
  requests = requests.map((request) => (request.id === id ? { ...request, cancelled: true } : request));
  emit();
  if (useServer) sync(id, before, "같이 취소", api.cancelRequest);
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

// 서버 모드의 답. 내 일정은 서버가 만들거나(수락) 지우므로(어렵다로 바꿈) 답한 뒤 내 일정 목록을 다시 읽는다.
// 서버 응답 전에는 내 답만 먼저 보이고, 일정 id 는 응답으로 채워진다.
function answerOnServer(request, answer, kind) {
  const before = requests;
  setReply(request.id, answer, null);
  const serverKind = kind === KIND.appointment ? 1 : kind === KIND.todo ? 2 : null;
  sync(request.id, before, "같이 답하기", (sid) => api.answerRequest(sid, answer, serverKind)).then(reloadItems);
}

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
  if (useServer) return answerOnServer(request, "accepted", kind);
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
  if (useServer) return answerOnServer(request, "declined", null);
  if (request.itemId) removeItem(request.itemId);
  setReply(id, "declined");
}
