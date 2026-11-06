import * as SecureStore from "expo-secure-store";

/**
 * 여행 모드 종료 시각과 백그라운드 수집 모드를 이 기기에 기억한다. 앱이 꺼진 채 깨어난 백그라운드 작업이 서버에 묻지 않고
 * "아직 보내지 않는다 / 종료됐으니 다시 보낸다"를 판단하려는 용도다. 좌표는 저장하지 않는다. 저장소를 못 쓰는 환경(웹)에서는 비어 있는 것으로 본다.
 */
const KEY_PAUSED_UNTIL = "gabee.location.paused_until";
const KEY_MODE = "gabee.location.bg_mode";

/** @param {string} key @returns {Promise<string | null>} */
async function read(key) {
  try {
    return (await SecureStore.getItemAsync(key)) || null;
  } catch {
    return null;
  }
}

/** @param {string} key @param {string | null} value */
async function write(key, value) {
  try {
    if (value) await SecureStore.setItemAsync(key, value);
    else await SecureStore.deleteItemAsync(key);
  } catch {
    /* 저장하지 못해도 서버 상태가 기준이라 다음 갱신에 다시 맞춘다 */
  }
}

/** @returns {Promise<string | null>} 기기에 저장한 여행 모드 종료 시각(ISO), 없으면 null */
export const loadPausedUntil = () => read(KEY_PAUSED_UNTIL);

/** @param {string | null} iso 여행 모드 종료 시각. null 이면 지운다 */
export const savePausedUntil = (iso) => write(KEY_PAUSED_UNTIL, iso);

/** @returns {Promise<"normal" | "waiting" | null>} 지금 시작해 둔 백그라운드 수집 모드 */
export async function loadBackgroundMode() {
  const mode = await read(KEY_MODE);
  return mode === "normal" || mode === "waiting" ? mode : null;
}

/** @param {"normal" | "waiting" | null} mode */
export const saveBackgroundMode = (mode) => write(KEY_MODE, mode);
