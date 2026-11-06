/**
 * 백그라운드 위치 수집의 순수 계산(앱 모듈 없이 시험할 수 있게 따로 둔다).
 */

/**
 * 이 기기에서 앱이 꺼져 있어도 위치를 모아야 하는지. 서버 스위치가 켜져 있고, 위치 공유와 백그라운드에 모두 동의했고,
 * 일시정지(여행 모드) 중이 아닐 때만 true 다. 하나라도 아니면 수집을 멈춘다.
 * @param {{ enabled: boolean, consent: boolean, background: boolean, paused: boolean } | null | undefined} me 서버가 알려 준 내 위치 상태
 * @returns {boolean}
 */
export function wantsBackground(me) {
  return Boolean(me && me.enabled && me.consent && me.background && !me.paused);
}

/**
 * expo-location 의 위치 하나를 서버가 받는 모양으로 바꾼다. 정확도가 음수(알 수 없음)이면 비운다.
 * @param {{ coords: { latitude: number, longitude: number, accuracy?: number | null }, timestamp: number }} loc
 * @returns {{ lat: number, lng: number, accuracy_m: number | null, recorded_at: string }}
 */
export function toPoint(loc) {
  const accuracy = loc.coords.accuracy;
  return {
    lat: loc.coords.latitude,
    lng: loc.coords.longitude,
    accuracy_m: typeof accuracy === "number" && accuracy >= 0 ? accuracy : null,
    recorded_at: new Date(loc.timestamp).toISOString(),
  };
}

/**
 * 한 번에 깨어난 위치들 중 서버로 올릴 것만 고른다(오래된 것부터 최대 max 개 가운데 가장 최근 쪽). 요청 수와 배터리를 아끼려는 상한이다.
 * @template T
 * @param {T[]} locations
 * @param {number} [max]
 * @returns {T[]}
 */
export function pickToSend(locations, max = 5) {
  return locations.length > max ? locations.slice(locations.length - max) : locations;
}

/**
 * 약관 스크롤이 맨 아래까지 내려왔는지(체크할 수 있는지). 안내가 짧아 스크롤이 필요 없는 경우도 true 다.
 * @param {{ contentOffset: { y: number }, layoutMeasurement: { height: number }, contentSize: { height: number } }} event 스크롤 이벤트의 nativeEvent
 * @param {number} [slack] 맨 아래로 보는 여유(px)
 * @returns {boolean}
 */
export function isScrolledToEnd({ contentOffset, layoutMeasurement, contentSize }, slack = 12) {
  return contentSize.height <= layoutMeasurement.height + slack || contentOffset.y + layoutMeasurement.height >= contentSize.height - slack;
}
