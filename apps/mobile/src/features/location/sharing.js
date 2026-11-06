import * as Location from "expo-location";

import { postLocationPoint } from "./api";

/** 앞에서 쓸 위치 권한을 요청한다(앱이 켜져 있는 동안 수집하는 기본 권한). @returns {Promise<boolean>} 허용 여부 */
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

/** @returns {Promise<{ foreground: string, background: string }>} 지금 위치 권한 상태(요청하지 않고 읽기만) */
export async function readPermissions() {
  const [fg, bg] = await Promise.all([Location.getForegroundPermissionsAsync(), Location.getBackgroundPermissionsAsync()]);
  return { foreground: fg.status, background: bg.status };
}
