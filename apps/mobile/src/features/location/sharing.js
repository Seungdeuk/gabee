import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { colors } from "@/theme";

import { postLocationPoint } from "./api";
import { LOCATION_TASK } from "./backgroundTask";

/** 앞에서 쓸 위치 권한을 요청한다(베타는 앱이 켜져 있는 동안만 수집한다). @returns {Promise<boolean>} 허용 여부 */
export async function requestForeground() {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === "granted";
}

/** @returns {Promise<{ lat: number, lng: number, accuracy_m: number | null }>} 지금 위치 */
export async function currentPoint() {
  const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  return { lat: loc.coords.latitude, lng: loc.coords.longitude, accuracy_m: loc.coords.accuracy ?? null };
}

/** 지금 위치를 한 번 재서 서버로 보낸다. @returns {Promise<import("./api").PointSaved>} */
export async function sendNow() {
  return postLocationPoint(await currentPoint());
}

/**
 * 시연용: 활동 구역을 빨리 만들려고 지금 위치 근처(수십 m)에서 잰 것처럼 위치 count 개를 보낸다. 내 위치만 쓴다.
 * @param {number} [count]
 * @returns {Promise<void>}
 */
export async function seedZoneNearHere(count = 5) {
  const base = await currentPoint();
  const now = Date.now();
  for (let i = 0; i < count; i += 1) {
    await postLocationPoint({
      lat: base.lat + ((i % 5) - 2) * 0.0001,
      lng: base.lng + ((i % 4) - 1.5) * 0.0001,
      accuracy_m: base.accuracy_m,
      recorded_at: new Date(now - (count - i) * 60000).toISOString(),
    });
  }
}

// 배터리를 아끼려고 1분마다 또는 50m 이상 움직였을 때만 받는다(Android 는 시간, iOS 는 거리 기준으로 동작한다).
const BACKGROUND_INTERVAL_MS = 60 * 1000;
const BACKGROUND_DISTANCE_M = 50;

/** @returns {Promise<boolean>} 이 기기에서 백그라운드 위치를 쓸 수 있는지(웹은 false, Expo Go 는 실제 시작할 때 막힌다) */
export async function canTrackInBackground() {
  if (Platform.OS === "web") return false;
  try {
    return await TaskManager.isAvailableAsync();
  } catch {
    return false;
  }
}

/**
 * 앞에서 쓰는 위치 권한에 이어 '항상 허용' 권한을 요청한다. 앞 권한을 먼저 받아야 한다.
 * @returns {Promise<"granted" | "foreground-only" | "denied">}
 */
export async function requestBackgroundPermission() {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status !== "granted") return "denied";
  const bg = await Location.requestBackgroundPermissionsAsync();
  return bg.status === "granted" ? "granted" : "foreground-only";
}

/**
 * 앱이 꺼져 있어도 위치를 받는 작업을 시작한다. 안드로이드는 '위치 공유 중' 알림이 계속 뜨고 아이폰은 위치 사용 표시가 뜬다(끌 수 없다).
 * 개발 빌드가 아니면(Expo Go 등) 시작할 수 없다.
 * @returns {Promise<"started" | "unavailable">}
 */
export async function startBackground() {
  if (!(await canTrackInBackground())) return "unavailable";
  try {
    if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) return "started";
    await Location.startLocationUpdatesAsync(LOCATION_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: BACKGROUND_INTERVAL_MS,
      distanceInterval: BACKGROUND_DISTANCE_M,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "가비 위치 공유 중",
        notificationBody: "동의한 가족에게 내 위치를 공유하고 있어요. 돌봄 탭에서 언제든 끌 수 있어요.",
        notificationColor: colors.primary,
      },
    });
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
}

/** @returns {Promise<boolean>} 이 기기에서 백그라운드 위치 작업이 돌고 있는지 */
export async function isBackgroundRunning() {
  try {
    return await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
  } catch {
    return false;
  }
}
