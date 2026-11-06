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

/**
 * 이 기기에서 위치를 어떻게 모을지. 서버 스위치·위치 공유 동의·백그라운드 동의가 모두 있어야 모은다.
 * 여행 모드(일시정지) 중에는 완전히 끄지 않고 저전력 대기(waiting)로 두어, 보내지는 않고 종료 후 스스로 다시 시작할 수 있게 한다.
 * @param {{ enabled: boolean, consent: boolean, background: boolean, paused: boolean } | null | undefined} me
 * @returns {"off" | "waiting" | "normal"}
 */
export function trackingMode(me) {
  if (!(me && me.enabled && me.consent && me.background)) return "off";
  return me.paused ? "waiting" : "normal";
}

/**
 * 기기에 저장해 둔 여행 종료 시각으로, 백그라운드 작업이 지금 위치를 보내도 되는지 정한다(서버에 묻지 않고 기기에서 판단).
 * @param {string | null | undefined} pausedUntilIso 기기에 저장한 종료 시각
 * @param {number} [now] 현재 시각(ms)
 * @returns {"none" | "paused" | "expired"} none=여행 모드 아님, paused=아직 보내지 않음, expired=종료됨(다시 보냄)
 */
export function localPauseState(pausedUntilIso, now = Date.now()) {
  if (!pausedUntilIso) return "none";
  const until = Date.parse(pausedUntilIso);
  if (Number.isNaN(until)) return "none";
  return now < until ? "paused" : "expired";
}
