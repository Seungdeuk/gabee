import * as SecureStore from "expo-secure-store";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { ApiError, configureAuth, hasSession, isApiConfigured, setSession } from "@/shared/api/client";
import { createTokenStore } from "@/shared/auth/tokenStore";

import { postLocationPoint } from "./api";
import { localPauseState, pickToSend, toPoint } from "./background";
import { LOCATION_TASK, startBackground, stopBackground } from "./backgroundControl";
import { loadPausedUntil, savePausedUntil } from "./pauseState";

const store = createTokenStore(SecureStore);

/**
 * 앱이 꺼진 채 깨어났을 때는 화면이 없어 로그인 상태가 메모리에 없다. 보안 저장소의 Refresh Token 으로 세션을 되살린다.
 * 앱이 켜져 있으면(같은 실행) 이미 세션이 있어 아무것도 하지 않는다 — Refresh Token 은 한 번 쓰면 폐기되므로 둘이 따로 갱신하지 않게 한다.
 * @returns {Promise<boolean>} 세션이 있는지
 */
async function ensureSession() {
  if (hasSession()) return true;
  const token = await store.load();
  if (!token) return false;
  configureAuth({ onRefreshTokenChanged: (next) => store.save(next), onSessionLost: () => store.clear() });
  setSession({ refreshToken: token });
  return true;
}

/**
 * 깨어날 때마다 기기에 저장한 여행 모드 종료 시각을 본다: 아직이면 보내지 않고 저전력 대기로 두고, 종료됐으면 기억을 지우고 정상 수집으로 돌아간다.
 * @returns {Promise<boolean>} 지금 위치를 서버로 보내도 되는지
 */
async function mayUpload() {
  const state = localPauseState(await loadPausedUntil());
  if (state === "paused") {
    await startBackground("waiting"); // 이미 대기 중이면 아무것도 하지 않는다
    return false;
  }
  if (state === "expired") {
    await savePausedUntil(null);
    await startBackground("normal");
  }
  return true;
}

// 모듈을 불러올 때 등록해야 앱이 꺼진 채 깨어나도 작업이 실행된다(루트 레이아웃에서 불러온다). 웹에는 없다.
if (Platform.OS !== "web") {
  TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
    if (error || !data?.locations?.length || !isApiConfigured()) return;
    try {
      if (!(await mayUpload())) return;
      if (!(await ensureSession())) return;
      for (const loc of pickToSend(data.locations)) {
        const res = await postLocationPoint(toPoint(loc));
        if (!res.saved && res.reason === "no_consent") {
          await stopBackground(); // 동의를 철회했으면 기기도 모으지 않는다
          return;
        }
        if (!res.saved && res.reason === "paused") return; // 여행 모드는 앱을 열 때 서버 상태에 맞춰 대기로 바뀐다
      }
    } catch (e) {
      if (e instanceof ApiError && (e.code === "session_expired" || e.status === 401)) await stopBackground();
      // 그 밖의 오류(네트워크 등)는 다음 갱신에 다시 보낸다. 좌표는 로그에 남기지 않는다
    }
  });
}
