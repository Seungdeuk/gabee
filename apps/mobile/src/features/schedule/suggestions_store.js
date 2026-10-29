import { useEffect, useSyncExternalStore } from "react";

import { isApiConfigured, legacyStorageScope } from "@/shared/api/client";
import { useAuth } from "@/shared/auth/AuthProvider";

import { loadSessions } from "../ai-assistant/storage/chatStore";
import * as api from "./api";
import { fromServerSuggestion } from "./suggestion_convert";
import { recentChatLines } from "./suggest_chat";

// 서버가 오늘 만들어 준 추천(대기 제안). 서버 주소가 있을 때만 쓴다. 화면이 처음 쓰일 때 한 번 불러오고,
// 실패하면 빈 목록으로 두고 다음에 다시 시도한다. 서버가 처음 만들 때는 몇 초 걸릴 수 있어 loading 을 함께 둔다.
const useServer = isApiConfigured();
let state = { list: [], loading: false, exhausted: false, loaded: false, failed: false };
let started = false;
const listeners = new Set();

// 개인 AI 채팅 저장 키(로그인 사용자 id). 채팅 화면(AiAssistantScreen)과 같은 규칙으로 useSuggestions 가 정한다. null 이면 채팅 없이 요청한다.
let chatScope = null;

/** 최근 내 채팅 줄. 대화를 못 읽거나 scope 가 없으면 빈 배열(읽기 실패가 추천 요청을 막지 않는다). */
async function chatLines() {
  if (!chatScope) return [];
  try {
    return recentChatLines(await loadSessions(chatScope), Date.now());
  } catch {
    return [];
  }
}

const emit = () => listeners.forEach((fn) => fn());
const subscribe = (fn) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const set = (patch) => {
  state = { ...state, ...patch };
  emit();
};

function load() {
  if (!useServer || started) return;
  started = true;
  set({ loading: true, loaded: false });
  chatLines().then(api.listSuggestions).then(
    (res) =>
      set({ list: res.suggestions.map(fromServerSuggestion), exhausted: Boolean(res.exhausted), loading: false, loaded: true, failed: false }),
    (error) => {
      // 403(AI 꺼짐)·429(한도) 포함: 빈 목록으로 두고(카드는 "추천해드릴게요"+새로고침), 다음에 화면이 열릴 때도 다시 시도한다.
      console.warn("[schedule] 추천 불러오기 실패", error?.message ?? error);
      started = false;
      set({ list: [], loading: false, loaded: true, failed: true });
    },
  );
}

/** 추천을 서버에 다시 요청한다(새로고침 버튼). 이미 불러오는 중이면 무시한다. */
export function reloadSuggestions() {
  if (state.loading) return;
  started = false;
  load();
}

/** 서버 추천 목록. @returns {{ list: ReturnType<typeof fromServerSuggestion>[], loading: boolean, exhausted: boolean, loaded: boolean, failed: boolean }} */
export function useSuggestions() {
  const auth = useAuth();
  const scope = auth.status === "loading" ? null : auth.user?.id ? `user-${auth.user.id}` : legacyStorageScope();
  useEffect(() => {
    chatScope = scope;
    load();
  }, [scope]);
  return useSyncExternalStore(subscribe, () => state);
}

/** 추가한 제안을 로컬 목록에서 뺀다(서버는 일정 등록과 함께 확정한다). @param {string} id */
export function markUsed(id) {
  if (!state.list.some((s) => s.id === id)) return;
  set({ list: state.list.filter((s) => s.id !== id) });
  // 받아 둔 제안을 다 썼는데 오늘 묶음이 남았으면 서버가 새로 만들어 준다.
  if (state.list.length === 0 && !state.exhausted) {
    started = false;
    load();
  }
}
