import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { sendLocations } from "../api";
import { LOCATION_TASK, toPoint } from "./task";

// 배터리를 아끼려고 15분마다 또는 200m 이상 움직였을 때만 받는다(후속에서 조정 가능).
const INTERVAL_MS = 15 * 60 * 1000;
const DISTANCE_M = 200;

/** @returns {Promise<boolean>} 이 기기에서 백그라운드 위치를 쓸 수 있는지(웹, Expo Go 에서는 false) */
export async function canTrackInBackground() {
  if (Platform.OS === "web") return false;
  try {
    return await TaskManager.isAvailableAsync();
  } catch {
    return false;
  }
}

/** 앞에서 쓸 위치 권한을 요청한다. @returns {Promise<boolean>} 허용 여부 */
export async function requestForeground() {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === "granted";
}

/**
 * 백그라운드 위치 수집을 시작한다. 앞에서 쓰는 권한이 먼저 있어야 하고, 항상 허용 권한이 없으면 시작하지 않는다.
 * @returns {Promise<"started" | "no-background-permission" | "unavailable">}
 */
export async function startBackground() {
  if (!(await canTrackInBackground())) return "unavailable";
  const bg = await Location.requestBackgroundPermissionsAsync();
  if (bg.status !== "granted") return "no-background-permission";
  if (!(await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK))) {
    await Location.startLocationUpdatesAsync(LOCATION_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: INTERVAL_MS,
      distanceInterval: DISTANCE_M,
      pausesUpdatesAutomatically: true,
      showsBackgroundLocationIndicator: true,
      foregroundService: {
        notificationTitle: "가비",
        notificationBody: "동의한 가족에게 내 위치를 공유하고 있어요",
      },
    });
  }
  return "started";
}

/** 백그라운드 위치 수집을 멈춘다(켜져 있지 않으면 아무것도 하지 않는다). */
export async function stopBackground() {
  if (!(await canTrackInBackground())) return;
  if (await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK)) {
    await Location.stopLocationUpdatesAsync(LOCATION_TASK);
  }
}

/** @returns {Promise<boolean>} 백그라운드 수집이 켜져 있는지 */
export async function isBackgroundRunning() {
  if (!(await canTrackInBackground())) return false;
  return Location.hasStartedLocationUpdatesAsync(LOCATION_TASK);
}

/** 지금 위치를 한 번 재서 서버로 보낸다. */
export async function sendNow() {
  const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  return sendLocations([toPoint(loc)]);
}
