import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { colors } from "@/theme";

import { loadBackgroundMode, saveBackgroundMode } from "./pauseState";

/** 백그라운드 위치 작업 이름. 시작·중지·확인에 같은 이름을 쓴다. */
export const LOCATION_TASK = "gabee-background-location";

/**
 * 수집 모드별 옵션.
 * - normal: 서버로 보내는 정상 수집(약 1분 또는 50m마다). 안드로이드는 '위치 공유 중' 알림이, 아이폰은 위치 사용 표시가 계속 보인다.
 * - waiting: 여행 모드 저전력 대기(약 30분 또는 500m, 낮은 정확도). 위치를 서버로 보내지 않고, 깨어날 때 종료 시각이 지났는지만 본다.
 */
const MODES = {
  normal: {
    accuracy: Location.Accuracy.Balanced,
    timeInterval: 60 * 1000,
    distanceInterval: 50,
    title: "가비 위치 공유 중",
    body: "동의한 가족에게 내 위치를 공유하고 있어요. 위치 탭에서 언제든 끌 수 있어요.",
  },
  waiting: {
    accuracy: Location.Accuracy.Low,
    timeInterval: 30 * 60 * 1000,
    distanceInterval: 500,
    title: "가비 여행 모드",
    body: "위치를 보내지 않고 있어요. 여행이 끝나면 자동으로 다시 공유해요.",
  },
};

/** @returns {Promise<boolean>} 이 기기에서 백그라운드 위치를 쓸 수 있는지(웹은 false, Expo Go 는 실제 시작할 때 막힌다) */
export async function canTrackInBackground() {
  if (Platform.OS === "web") return false;
  try {
    return await TaskManager.isAvailableAsync();
  } catch {
    return false;
  }
}

/** @returns {Promise<boolean>} 이 기기에서 백그라운드 위치 작업이 돌고 있는지 */
export async function isBackgroundRunning() {
  try {
    return await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  } catch {
    return false;
  }
}

/**
 * 앱이 꺼져 있어도 위치를 받는 작업을 시작하거나, 이미 돌고 있는데 모드가 다르면 옵션을 바꿔 다시 시작한다.
 * 개발 빌드가 아니면(Expo Go 등) 시작할 수 없다.
 * @param {"normal" | "waiting"} [mode]
 * @returns {Promise<"started" | "unavailable">}
 */
export async function startBackground(mode = "normal") {
  if (!(await canTrackInBackground())) return "unavailable";
  const m = MODES[mode];
  try {
    if (await isBackgroundRunning()) {
      if ((await loadBackgroundMode()) === mode) return "started";
      await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    }
    await Location.startLocationUpdatesAsync(LOCATION_TASK, {
      accuracy: m.accuracy,
      timeInterval: m.timeInterval,
      distanceInterval: m.distanceInterval,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: true,
      foregroundService: { notificationTitle: m.title, notificationBody: m.body, notificationColor: colors.primary },
    });
    await saveBackgroundMode(mode);
    return "started";
  } catch {
    return "unavailable";
  }
}

/** 백그라운드 위치 작업을 멈춘다(켜져 있지 않거나 쓸 수 없는 기기면 아무것도 하지 않는다). */
export async function stopBackground() {
  try {
    if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) {
      await Location.stopLocationUpdatesAsync(LOCATION_TASK);
    }
  } catch {
    /* 이 기기에서 시작한 적이 없다 */
  }
  await saveBackgroundMode(null);
}
