// 채팅 앨범 묶음의 순수 함수(화면·네트워크와 분리해 시험한다). 사진 내용은 어디에도 기록하지 않는다.

/** 한 번에 올릴 수 있는 사진 수. */
export const MAX_ALBUM_PHOTOS = 10;

/** 말풍선에 보이는 칸 수(넘치면 마지막 칸에 "+N"). */
export const ALBUM_VISIBLE = 4;

/** 앨범 말풍선의 가로(dp). */
export const ALBUM_WIDTH = 220;

const GAP = 2;

/**
 * 한 번에 올리는 사진들이 함께 가질 묶음 번호를 만든다(서버 규칙: 영문·숫자·_- 8~32자). 시각과 난수를 섞어 호출마다 다르다.
 * @param {number} [now] epoch 밀리초
 * @param {() => number} [rand] 0 이상 1 미만 난수
 * @returns {string}
 */
export function makeBatchId(now = Date.now(), rand = Math.random) {
  const noise = rand().toString(36).slice(2, 10).padEnd(8, "0");
  return `${Math.max(0, Math.floor(now)).toString(36)}${noise}`;
}

/**
 * 앨범 말풍선의 칸 배치. 2장은 나란히, 3장은 위 한 장 + 아래 두 장, 4장 이상은 2×2(남는 수는 more).
 * @param {number} count 묶음의 사진 수
 * @param {number} [width] 말풍선 안쪽 가로
 * @returns {{ cells: { width: number, height: number }[], more: number }}
 */
export function albumCells(count, width = ALBUM_WIDTH) {
  const n = Math.max(0, Math.floor(count) || 0);
  const half = Math.floor((width - GAP) / 2);
  if (n <= 2) return { cells: Array.from({ length: n }, () => ({ width: half, height: half })), more: 0 };
  if (n === 3) return { cells: [{ width, height: Math.round(width * 0.66) }, { width: half, height: half }, { width: half, height: half }], more: 0 };
  return { cells: Array.from({ length: ALBUM_VISIBLE }, () => ({ width: half, height: half })), more: Math.max(0, n - ALBUM_VISIBLE) };
}

/**
 * 앨범에서 메시지가 몇 번째 사진인지(없으면 0, 뷰어를 첫 사진에서 연다).
 * @param {{ id: number | string }[]} album
 * @param {number | string} messageId
 * @returns {number}
 */
export function albumIndexOf(album, messageId) {
  const i = (album ?? []).findIndex((m) => String(m.id) === String(messageId));
  return i < 0 ? 0 : i;
}

/**
 * 앨범으로 묶일 수 있는 서버 메시지인지: 묶음 번호가 있는 사진이고 지우지 않았고 보내는 중이 아니다.
 * @param {object} message
 * @returns {boolean}
 */
export function isAlbumPhoto(message) {
  return Boolean(message && !message.deleted && !message.clientId && !message.localNote && message.attachment?.kind === "image" && message.attachment?.batch_id);
}
