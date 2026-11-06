import * as Location from "expo-location";
import * as SecureStore from "expo-secure-store";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { ApiError, configureAuth, hasSession, isApiConfigured, setSession } from "@/shared/api/client";
import { createTokenStore } from "@/shared/auth/tokenStore";

import { postLocationPoint } from "./api";
import { pickToSend, toPoint } from "./background";

/** 백그라운드 위치 작업 이름. 시작·중지·확인에 같은 이름을 쓴다. */
export const LOCATION_TASK = "gabee-background-location";

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

/** 서버가 더는 받지 않거나(철회·일시정지) 로그인이 풀렸으면 이 기기의 수집을 멈춘다. */
async function stopUpdates() {
  try {
    if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) {
      await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    }
  } catch {
    /* 이미 멈췄거나 이 기기에서 쓸 수 없는 경우 */
  }
}

// 모듈을 불러올 때 등록해야 앱이 꺼진 채 깨어나도 작업이 실행된다(루트 레이아웃에서 불러온다). 웹에는 없다.
if (Platform.OS !== "web") {
  TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
    if (error || !data?.locations?.length || !isApiConfigured()) return;
    try {
      if (!(await ensureSession())) return;
      for (const loc of pickToSend(data.locations)) {
        const res = await postLocationPoint(toPoint(loc));
        if (!res.saved && (res.reason === "paused" || res.reason === "no_consent")) {
          await stopUpdates(); // 서버가 받지 않는 상태면 기기도 모으지 않는다
          return;
        }
      }
    } catch (e) {
      if (e instanceof ApiError && (e.code === "session_expired" || e.status === 401)) await stopUpdates();
      // 그 밖의 오류(네트워크 등)는 다음 갱신에 다시 보낸다. 좌표는 로그에 남기지 않는다
    }
  });
}
