import AsyncStorage from "@react-native-async-storage/async-storage";

// 열어 본 공지 id 를 이 폰에만 저장한다(서버에는 보내지 않는다). 폰을 바꾸면 다시 '새 글'로 보인다.
// 읽기·쓰기가 실패해도 화면은 그대로 동작한다(못 읽으면 모두 새 글).
const KEY = "gabee.notices.read.v1";
const MAX = 300; // 서버가 최대 100건을 주므로 넉넉히 둔다

/** @returns {Promise<Set<string>>} */
export async function loadReadIds() {
  try {
    const list = JSON.parse((await AsyncStorage.getItem(KEY)) ?? "[]");
    return new Set(Array.isArray(list) ? list.filter((v) => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

/** @param {Set<string>} ids */
export async function saveReadIds(ids) {
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify([...ids].slice(-MAX)));
  } catch {
    // 저장이 안 돼도 이번 화면에서는 읽음으로 보인다
  }
}
