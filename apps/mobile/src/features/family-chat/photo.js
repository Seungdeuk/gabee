/**
 * 채팅 사진의 순수 로직(화면·네트워크와 무관): 한도, 파일 이름·형식, 표시 크기(갤러리 선택은 pickPhoto.js).
 * 서버 계약은 PR #60(POST /family-chat/photos)이 기준이다. 사진 내용은 어디에도 기록하지 않는다.
 */
/** 서버가 받는 한도(8MB). 서버가 다시 확인하지만 큰 파일은 올리기 전에 알려 준다. */
export const MAX_CHAT_PHOTO_BYTES = 8 * 1024 * 1024;

/** 웹에서 올리기 전에 줄일 긴 변(px)과 JPEG 품질. */
export const WEB_MAX_SIDE = 2048;
export const WEB_JPEG_QUALITY = 0.85;

/** 네이티브 갤러리에서 줄여 받는 품질(0~1). */
export const PICKER_QUALITY = 0.8;

/** 말풍선 안 썸네일이 차지할 수 있는 최대 크기(dp). */
export const THUMB_MAX_WIDTH = 220;
export const THUMB_MAX_HEIGHT = 280;

const MIME_BY_EXT = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" };

const extOf = (text) => /\.([a-z0-9]+)(?:[?#].*)?$/i.exec(text ?? "")?.[1]?.toLowerCase() ?? "";

/**
 * 올릴 파일의 형식. asset 의 mimeType 이 이미지면 그대로, 없으면 이름·주소의 확장자로 추정하고 모르면 JPEG.
 * @param {{ uri?: string, fileName?: string | null, mimeType?: string }} asset
 * @returns {string}
 */
export function chatPhotoMimeType(asset) {
  if (asset?.mimeType?.startsWith("image/")) return asset.mimeType;
  return MIME_BY_EXT[extOf(asset?.fileName) || extOf(asset?.uri)] ?? "image/jpeg";
}

/**
 * 올릴 파일 이름. 이름이 없으면 형식에 맞는 확장자로 만든다.
 * @param {{ uri?: string, fileName?: string | null, mimeType?: string }} asset
 * @returns {string}
 */
export function chatPhotoFileName(asset) {
  if (asset?.fileName) return asset.fileName;
  const ext = Object.entries(MIME_BY_EXT).find(([, mime]) => mime === chatPhotoMimeType(asset))?.[0] ?? "jpg";
  return `photo.${ext}`;
}

/**
 * 고른 사진이 한도(8MB)를 넘는지. 크기를 모르면 false 라서 서버 판단에 맡긴다.
 * @param {{ fileSize?: number | null }} asset
 * @returns {boolean}
 */
export const isChatPhotoTooLarge = (asset) => typeof asset?.fileSize === "number" && asset.fileSize > MAX_CHAT_PHOTO_BYTES;

/**
 * 원본 비율을 지키면서 최대 폭·높이 안에 들어가는 표시 크기(dp). 확대하지 않는다.
 * 너비·높이를 모르거나 올바르지 않으면 최대 폭의 정사각형(레이아웃이 점프하지 않게).
 * @param {number | null | undefined} width 원본 너비
 * @param {number | null | undefined} height 원본 높이
 * @param {number} [maxWidth]
 * @param {number} [maxHeight]
 * @returns {{ width: number, height: number }}
 */
export function fitSize(width, height, maxWidth = THUMB_MAX_WIDTH, maxHeight = THUMB_MAX_HEIGHT) {
  const w = Number(width);
  const h = Number(height);
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return { width: maxWidth, height: maxWidth };
  const scale = Math.min(1, maxWidth / w, maxHeight / h);
  return { width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) };
}
