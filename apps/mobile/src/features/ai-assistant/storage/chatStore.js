import AsyncStorage from "@react-native-async-storage/async-storage";

/**
 * 대화 목록을 이 기기에만 저장한다(서버에는 보내지 않는다).
 * 키에 로그인한 사용자 id(scope)를 넣어서, 같은 폰에서 다른 사람이 로그인하면 앞사람의 대화가 보이지 않게 한다.
 * 나중에 서버 저장으로 바꾸면 이 파일의 세 함수만 바꾼다.
 *
 * 대화 한 건: { id, title, updatedAt, messages }
 */
const MAX_SESSIONS = 30;
const MAX_MESSAGES = 200;

const key = (scope) => `gabee.chat.sessions.v1.${scope}`;

/** 저장된 대화를 최근 순으로 돌려준다. 저장소를 못 읽으면 빈 목록. */
export async function loadSessions(scope) {
  try {
    const raw = await AsyncStorage.getItem(key(scope));
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.sort((a, b) => b.updatedAt - a.updatedAt) : [];
  } catch {
    return [];
  }
}

async function write(scope, list) {
  try {
    await AsyncStorage.setItem(key(scope), JSON.stringify(list.slice(0, MAX_SESSIONS)));
  } catch {
    // 저장이 안 돼도 대화는 계속 쓸 수 있다
  }
}

/** 대화 한 건을 새로 만들거나 덮어쓴다. */
export async function saveSession(scope, session) {
  const list = (await loadSessions(scope)).filter((s) => s.id !== session.id);
  const trimmed = { ...session, messages: session.messages.slice(-MAX_MESSAGES) };
  const next = [trimmed, ...list].sort((a, b) => b.updatedAt - a.updatedAt);
  await write(scope, next);
  return next;
}

export async function deleteSession(scope, id) {
  const next = (await loadSessions(scope)).filter((s) => s.id !== id);
  await write(scope, next);
  return next;
}
