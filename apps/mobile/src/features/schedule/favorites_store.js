import AsyncStorage from "@react-native-async-storage/async-storage";

import { restoreHidden, serializeHidden } from "./favorites";

// "누구" 칩 줄에서 뺀 사람 목록을 이 폰에만 저장한다(서버에는 보내지 않는다). 키에 내 사용자 id 를 넣어 로그인한 사람마다 따로 둔다.
// 읽기·쓰기가 실패해도 화면은 그대로 동작한다(못 읽으면 아무도 안 뺀 상태).
const key = (scope) => `gabee.schedule.hiddenWho.v1.${scope}`;

/** @returns {Promise<string[]>} */
export async function loadHiddenWho(scope) {
  try {
    return restoreHidden(await AsyncStorage.getItem(key(scope)));
  } catch {
    return [];
  }
}

export async function saveHiddenWho(scope, hiddenIds) {
  try {
    await AsyncStorage.setItem(key(scope), serializeHidden(hiddenIds));
  } catch {
    // 저장이 안 돼도 이번 화면에서는 계속 쓸 수 있다
  }
}
