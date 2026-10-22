import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { sendLocations } from "../api";

/** 백그라운드 위치 작업 이름. startLocationUpdatesAsync 와 같은 이름이어야 한다. */
export const LOCATION_TASK = "gabee-care-location";

/**
 * expo-location 위치 하나를 서버로 보낼 모양으로 바꾼다.
 * @param {{ coords: { latitude: number, longitude: number, accuracy: number | null }, timestamp: number }} loc
 * @returns {import("../api").LocationPoint}
 */
export const toPoint = (loc) => ({
  lat: loc.coords.latitude,
  lng: loc.coords.longitude,
  accuracy_m: loc.coords.accuracy ?? null,
  recorded_at: new Date(loc.timestamp).toISOString(),
});

// 전역 범위에서 등록해야 앱이 백그라운드에서 깨어났을 때도 작업이 실행된다(컴포넌트 안에서 부르면 안 된다).
// 웹에는 백그라운드 작업이 없다. 위치 좌표는 로그에 남기지 않고, 보내지 못하면 다음 주기에 다시 보낸다.
if (Platform.OS !== "web") {
  TaskManager.defineTask(LOCATION_TASK, async ({ data, error }) => {
    if (error || !data?.locations?.length) return;
    try {
      await sendLocations(data.locations.map(toPoint));
    } catch {
      // 동의 철회·네트워크 오류 등: 조용히 넘어가고 다음 주기에 다시 시도한다
    }
  });
}
