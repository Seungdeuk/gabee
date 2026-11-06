const M_PER_DEG = 111320; // 위도 1도가 약 111.32km
const MIN_SPAN_M = 600; // 점이 한 곳에 몰려도 지도가 너무 확대되지 않게 하는 최소 폭(m)

/**
 * 위도·경도 점들을 지도 상자(px) 안의 위치로 바꾼다. 지도 타일 없이 점·활동 구역의 상대 위치만 그린다.
 * 위도 방향은 위가 북쪽이다.
 * @param {{ id: string, lat: number, lng: number, zone?: { center_lat: number, center_lng: number, radius_m: number } | null }[]} items
 * @param {{ width: number, height: number, pad?: number }} box
 * @returns {{ id: string, x: number, y: number, zone: { x: number, y: number, r: number } | null }[]}
 */
export function projectItems(items, { width, height, pad = 28 }) {
  if (!items.length) return [];
  const lat0 = items.reduce((a, i) => a + i.lat, 0) / items.length;
  const kx = M_PER_DEG * Math.cos((lat0 * Math.PI) / 180);
  const toM = (lat, lng) => ({ x: lng * kx, y: lat * M_PER_DEG });
  const pts = [];
  for (const i of items) {
    const p = toM(i.lat, i.lng);
    pts.push(p);
    if (i.zone) {
      const c = toM(i.zone.center_lat, i.zone.center_lng);
      const r = i.zone.radius_m;
      pts.push({ x: c.x - r, y: c.y - r }, { x: c.x + r, y: c.y + r });
    }
  }
  const minX = Math.min(...pts.map((p) => p.x));
  const maxX = Math.max(...pts.map((p) => p.x));
  const minY = Math.min(...pts.map((p) => p.y));
  const maxY = Math.max(...pts.map((p) => p.y));
  const spanX = Math.max(maxX - minX, MIN_SPAN_M);
  const spanY = Math.max(maxY - minY, MIN_SPAN_M);
  const scale = Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY);
  const offX = (width - spanX * scale) / 2 - (minX - (spanX - (maxX - minX)) / 2) * scale;
  const offY = (height - spanY * scale) / 2 + (maxY + (spanY - (maxY - minY)) / 2) * scale;
  const place = (m) => ({ x: m.x * scale + offX, y: offY - m.y * scale });
  return items.map((i) => {
    const p = place(toM(i.lat, i.lng));
    const zone = i.zone ? { ...place(toM(i.zone.center_lat, i.zone.center_lng)), r: i.zone.radius_m * scale } : null;
    return { id: i.id, x: p.x, y: p.y, zone };
  });
}

/**
 * 마지막 위치를 잰 지 얼마나 됐는지를 짧은 말로 바꾼다.
 * @param {string | null | undefined} iso 위치를 잰 시각(ISO)
 * @param {number} [now] 현재 시각(ms), 시험용
 * @returns {string}
 */
export function agoText(iso, now = Date.now()) {
  if (!iso) return "";
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "방금";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours}시간 전` : "하루 넘게 전";
}
