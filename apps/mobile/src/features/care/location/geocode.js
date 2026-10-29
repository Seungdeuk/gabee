import * as Location from "expo-location";

import { placeKey, placeLabel } from "./place";

/**
 * 좌표를 "시·동" 이름으로 바꾼다. **기기의 주소 변환 서비스(안드로이드는 구글 서비스)에 좌표를 보낸다** — 가족 위치를 보는 사람의 기기에서
 * 보여 줄 때만 부르고, 서버에는 보내지 않는다(2026-10-28 사용자 승인). 한 번에 하나씩 부르고(여러 개를 동시에 부르면 오류가 난다)
 * 같은 동네(소수 셋째 자리)는 결과를 다시 쓴다. 웹·권한 없음·실패는 모두 null 이다.
 */
const cache = new Map();
let chain = Promise.resolve();

/**
 * @param {number} lat @param {number} lng
 * @returns {Promise<string | null>} 예: "서울특별시 중구 명동", 알 수 없으면 null
 */
export function placeName(lat, lng) {
  const key = placeKey(lat, lng);
  if (cache.has(key)) return cache.get(key);
  const result = (chain = chain.then(async () => {
    try {
      const permission = await Location.getForegroundPermissionsAsync();
      if (!permission.granted) return null; // 여기서 권한을 새로 묻지 않는다
      const [address] = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
      return placeLabel(address);
    } catch {
      return null;
    }
  }));
  cache.set(key, result);
  result.then((name) => {
    if (name === null) cache.delete(key); // 실패는 기억하지 않는다(나중에 권한을 주면 다시 시도)
  });
  return result;
}
