/**
 * 꼭짓점이 위로 향한 정육각형의 여섯 꼭짓점(SVG `points` 문자열, 위쪽 꼭짓점부터 시계 방향).
 * @param {number} size 그릴 정사각형의 한 변
 * @param {number} [inset] 테두리가 잘리지 않게 안쪽으로 줄이는 거리(테두리 두께의 절반 이상)
 * @returns {string} "x,y x,y x,y x,y x,y x,y"
 */
export function hexPoints(size, inset = 0) {
  const center = size / 2;
  const radius = center - inset;
  const points = [];
  for (let i = 0; i < 6; i += 1) {
    const angle = ((-90 + 60 * i) * Math.PI) / 180;
    points.push(`${(center + radius * Math.cos(angle)).toFixed(2)},${(center + radius * Math.sin(angle)).toFixed(2)}`);
  }
  return points.join(" ");
}
