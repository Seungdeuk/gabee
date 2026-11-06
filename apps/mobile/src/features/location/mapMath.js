/**
 * 타일 지도(OpenStreetMap 방식, 한 타일 256px)를 그리는 순수 계산. 앱 모듈 없이 시험할 수 있게 따로 둔다.
 * 월드 픽셀은 줌 z 에서 지구 전체를 256 * 2^z 픽셀 정사각형으로 폈을 때의 좌표다.
 */
export const TILE = 256;
export const MIN_ZOOM = 3;
export const MAX_ZOOM = 18;
const MAX_LAT = 85.0511287798;

/**
 * 위도·경도를 줌 z 의 월드 픽셀로 바꾼다.
 * @param {number} lat
 * @param {number} lng
 * @param {number} zoom
 * @returns {{ x: number, y: number }}
 */
export function worldPx(lat, lng, zoom) {
  const scale = TILE * 2 ** zoom;
  const clamped = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const sin = Math.sin((clamped * Math.PI) / 180);
  return {
    x: ((lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale,
  };
}

/**
 * 화면 한가운데가 center 가 되도록 점이 화면의 어디(px)에 오는지 구한다.
 * @param {{ lat: number, lng: number }} point
 * @param {{ lat: number, lng: number }} center
 * @param {number} zoom
 * @param {{ width: number, height: number }} size
 * @returns {{ x: number, y: number }}
 */
export function project(point, center, zoom, size) {
  const p = worldPx(point.lat, point.lng, zoom);
  const c = worldPx(center.lat, center.lng, zoom);
  return { x: size.width / 2 + (p.x - c.x), y: size.height / 2 + (p.y - c.y) };
}

/**
 * 화면 1px 이 땅에서 몇 m 인지(그 위도에서).
 * @param {number} lat
 * @param {number} zoom
 * @returns {number}
 */
export function metersPerPixel(lat, zoom) {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
}

/**
 * 화면을 채우는 데 필요한 타일 목록과 각 타일이 놓일 화면 위치.
 * 경도 방향은 지구를 한 바퀴 돌아 이어 붙이고, 위도 방향은 지도 밖이면 빼 둔다.
 * @param {{ lat: number, lng: number }} center
 * @param {number} zoom
 * @param {{ width: number, height: number }} size
 * @returns {{ key: string, z: number, x: number, y: number, left: number, top: number }[]}
 */
export function tilesFor(center, zoom, size) {
  const c = worldPx(center.lat, center.lng, zoom);
  const originX = c.x - size.width / 2;
  const originY = c.y - size.height / 2;
  const n = 2 ** zoom;
  const out = [];
  for (let ty = Math.floor(originY / TILE); ty <= Math.floor((originY + size.height) / TILE); ty += 1) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = Math.floor(originX / TILE); tx <= Math.floor((originX + size.width) / TILE); tx += 1) {
      out.push({
        key: `${zoom}/${tx}/${ty}`,
        z: zoom,
        x: ((tx % n) + n) % n,
        y: ty,
        left: tx * TILE - originX,
        top: ty * TILE - originY,
      });
    }
  }
  return out;
}

/**
 * OpenStreetMap 표준 타일 주소.
 * @param {{ z: number, x: number, y: number }} tile
 * @returns {string}
 */
export const tileUrl = (tile) => `https://tile.openstreetmap.org/${tile.z}/${tile.x}/${tile.y}.png`;

/**
 * 줌을 허용 범위 안으로 맞춘다.
 * @param {number} zoom
 * @returns {number}
 */
export const clampZoom = (zoom) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(zoom)));

/** 위치를 아직 모를 때 지도를 여는 기본 중심(서울시청). */
export const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 };
