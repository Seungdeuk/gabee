import * as Location from "expo-location";

import { postLocationPoint } from "./api";

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
export async function seedZoneNearHere(count = 20) {
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
