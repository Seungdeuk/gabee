// 사진 확대(핀치·드래그·두 번 탭)의 계산 규칙. 순수 함수라서 시험(tests/zoommath.test.js)이 가능하고,
// 'worklet' 표시가 있어 제스처 콜백(UI 스레드)에서도 그대로 부른다.
// 이동 값은 화면 가운데를 0 으로 하는 거리다. 화면 위치 = 이동 값 + 배율 × 사진 안의 위치.

export const MIN_SCALE = 1; // 손을 떼면 원래 크기보다 작게 남지 않는다
export const MAX_SCALE = 5;
export const PINCH_MIN_SCALE = 0.8; // 오므리는 중에는 조금 더 줄어들어 손에 반응이 느껴지게 하고, 떼면 1배로 돌아온다
export const DOUBLE_TAP_SCALE = 2.5; // 두 번 누르면 이 배율로 확대한다
const ZOOMED = MIN_SCALE + 0.05; // 이 배율을 넘으면 "확대된 상태"로 본다

/**
 * 손을 뗀 뒤의 배율: 1배~5배.
 * @param {number} scale
 * @returns {number}
 */
export function clampScale(scale) {
  "worklet";
  if (!Number.isFinite(scale)) return MIN_SCALE;
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/**
 * 오므리고 벌리는 중의 배율: 0.8배~5배.
 * @param {number} scale
 * @returns {number}
 */
export function clampPinchScale(scale) {
  "worklet";
  if (!Number.isFinite(scale)) return MIN_SCALE;
  return Math.min(MAX_SCALE, Math.max(PINCH_MIN_SCALE, scale));
}

/**
 * 사진이 화면에 잘리지 않게 맞췄을 때(contain) 1배에서 실제로 보이는 크기.
 * @param {number} viewWidth 화면 너비
 * @param {number} viewHeight 화면 높이
 * @param {number} ratio 사진의 가로÷세로. 아직 모르면 0(화면 크기로 본다)
 * @returns {{ width: number, height: number }}
 */
export function fittedSize(viewWidth, viewHeight, ratio) {
  "worklet";
  if (!(ratio > 0) || !(viewHeight > 0)) return { width: viewWidth, height: viewHeight };
  if (viewWidth / viewHeight > ratio) return { width: viewHeight * ratio, height: viewHeight }; // 화면이 더 넓다: 높이에 맞춘다
  return { width: viewWidth, height: viewWidth / ratio };
}

/**
 * 한 축으로 옮길 수 있는 거리. 사진이 화면보다 커진 만큼의 절반이고, 사진이 화면보다 작으면 0(가운데 고정)이다.
 * @param {number} contentSize 그 축의 1배 사진 길이
 * @param {number} viewSize 그 축의 화면 길이
 * @param {number} scale 배율
 * @returns {number}
 */
export function maxPan(contentSize, viewSize, scale) {
  "worklet";
  return Math.max(0, (contentSize * scale - viewSize) / 2);
}

/**
 * 이동 값을 사진 가장자리가 화면 안쪽으로 들어오지 않는 범위로 맞춘다.
 * @param {number} value 원하는 이동 값
 * @param {number} contentSize 그 축의 1배 사진 길이
 * @param {number} viewSize 그 축의 화면 길이
 * @param {number} scale 배율
 * @returns {number}
 */
export function clampPan(value, contentSize, viewSize, scale) {
  "worklet";
  const limit = maxPan(contentSize, viewSize, scale);
  return Math.min(limit, Math.max(-limit, value)) || 0; // -0 과 숫자가 아닌 값은 0 으로
}

/**
 * 손가락 사이 지점이 그 자리에 머물도록 배율이 바뀐 뒤의 이동 값을 구한다.
 * @param {number} pan 지금 이동 값
 * @param {number} focal 손가락 지점(화면 가운데를 0 으로 한 거리)
 * @param {number} from 지금 배율
 * @param {number} to 새 배율
 * @returns {number}
 */
export function zoomAround(pan, focal, from, to) {
  "worklet";
  if (!Number.isFinite(focal) || !(from > 0)) return pan;
  return focal - (focal - pan) * (to / from);
}

/**
 * 두 번 눌렀을 때 다음 배율: 확대돼 있으면 원래 크기로, 아니면 2.5배로.
 * @param {number} scale 지금 배율
 * @returns {number}
 */
export function doubleTapScale(scale) {
  "worklet";
  return scale > ZOOMED ? MIN_SCALE : DOUBLE_TAP_SCALE;
}
