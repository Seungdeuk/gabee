/**
 * 위치 표시용 순수 함수(기기 모듈에 의존하지 않아 node 시험에서 쓴다).
 * 좌표 → 주소 변환 호출은 `geocode.js` 에 있다.
 */

/**
 * 주소 변환 결과에서 "시·동" 정도의 짧은 이름을 만든다. 나라마다 칸의 뜻이 달라서 있는 칸만 쓰고 같은 말은 한 번만 쓴다.
 * 시(city → subregion → region)와 동(district)을 이 순서로 합친다. 도로명·번지는 쓰지 않는다(너무 자세한 위치라서).
 * @param {{ city?: string | null, district?: string | null, subregion?: string | null, region?: string | null } | null | undefined} address expo-location 의 LocationGeocodedAddress
 * @returns {string | null} 예: "서울특별시 중구 명동", 만들 수 없으면 null
 */
export function placeLabel(address) {
  if (!address) return null;
  const parts = [];
  for (const part of [address.city || address.subregion || address.region, address.district]) {
    const text = typeof part === "string" ? part.trim() : "";
    if (text && !parts.includes(text)) parts.push(text);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

/**
 * 같은 동네의 좌표는 한 번만 변환하도록 소수 셋째 자리(약 100m)로 줄인 키.
 * @param {number} lat @param {number} lng @returns {string}
 */
export const placeKey = (lat, lng) => `${lat.toFixed(3)},${lng.toFixed(3)}`;

/**
 * 지도 앱·브라우저에서 이 좌표를 여는 주소(사용자가 "지도에서 보기"를 눌렀을 때만 쓴다).
 * @param {number} lat @param {number} lng @returns {string}
 */
export const mapUrl = (lat, lng) => `https://www.google.com/maps/search/?api=1&query=${lat},${lng}`;

/**
 * 받은 시각을 "10월 28일 오전 11:40"처럼 보여 준다(기기 시간대).
 * @param {string | null | undefined} iso ISO 시각 @returns {string} 읽을 수 없으면 ""
 */
export function timeText(iso) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  const h = d.getHours();
  const ampm = h < 12 ? "오전" : "오후";
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${ampm} ${hour12}:${String(d.getMinutes()).padStart(2, "0")}`;
}
