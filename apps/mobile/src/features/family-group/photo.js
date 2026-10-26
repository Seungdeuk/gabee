/**
 * 프로필 사진의 순수 로직(화면·네트워크와 무관): 크기 한도, 파일 이름·형식, 오류 문구.
 */
import { familyErrorMessage } from "./messages";

/** 서버가 받는 한도(2MB). 서버가 다시 확인하지만 큰 파일은 올리기 전에 알려 준다. */
export const MAX_PHOTO_BYTES = 2 * 1024 * 1024;

const MIME_BY_EXT = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" };

const extOf = (text) => /\.([a-z0-9]+)(?:[?#].*)?$/i.exec(text ?? "")?.[1]?.toLowerCase() ?? "";

/**
 * 올릴 파일의 형식. asset 의 mimeType 이 이미지면 그대로, 없으면 이름·주소의 확장자로 추정하고 모르면 JPEG.
 * @param {{ uri?: string, fileName?: string | null, mimeType?: string }} asset
 * @returns {string}
 */
export function photoMimeType(asset) {
  if (asset?.mimeType?.startsWith("image/")) return asset.mimeType;
  return MIME_BY_EXT[extOf(asset?.fileName) || extOf(asset?.uri)] ?? "image/jpeg";
}

/**
 * 올릴 파일 이름. 이름이 없으면 형식에 맞는 확장자로 만든다.
 * @param {{ uri?: string, fileName?: string | null, mimeType?: string }} asset
 * @returns {string}
 */
export function photoFileName(asset) {
  if (asset?.fileName) return asset.fileName;
  const ext = Object.entries(MIME_BY_EXT).find(([, mime]) => mime === photoMimeType(asset))?.[0] ?? "jpg";
  return `profile.${ext}`;
}

/**
 * 고른 사진이 한도(2MB)를 넘는지. 크기를 모르면(웹 등) false 라서 서버 판단에 맡긴다.
 * @param {{ fileSize?: number | null }} asset
 * @returns {boolean}
 */
export const isPhotoTooLarge = (asset) => typeof asset?.fileSize === "number" && asset.fileSize > MAX_PHOTO_BYTES;

const BY_CODE = {
  photo_too_large: "사진이 너무 커요. 더 작게 자르거나 다른 사진을 골라 주세요",
  invalid_image: "사진 파일이 아니거나 너무 커요. 더 작게 자르거나 다른 사진을 골라 주세요",
  photo_busy: "지금 사진을 처리하는 요청이 많아요. 잠시 후 다시 해 주세요",
  too_many_uploads: "사진을 너무 자주 바꿨어요. 잠시 후 다시 해 주세요",
};

/**
 * 사진 올리기·지우기 오류(ApiError)를 사용자 문구로. 사진 전용 코드가 아니면 가족 화면 공통 문구를 쓴다.
 * @param {{ code?: string, status?: number, message?: string, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function photoErrorMessage(error) {
  if (!error) return "";
  const code = BY_CODE[error.code] ? error.code : error.status === 413 ? "photo_too_large" : error.status === 429 ? "too_many_uploads" : "";
  const base = code === "invalid_image" && error.message ? error.message : BY_CODE[code];
  if (!base) return familyErrorMessage(error);
  if (code === "too_many_uploads" && error.retryAfter) {
    const wait = error.retryAfter < 60 ? `${error.retryAfter}초` : `${Math.ceil(error.retryAfter / 60)}분`;
    return `${base} (${wait} 뒤에 다시 할 수 있어요)`;
  }
  return base;
}

/** 웹에서 올리기 전에 줄일 긴 변의 한도(px)와 JPEG 품질. */
export const WEB_MAX_SIDE = 1024;
export const WEB_JPEG_QUALITY = 0.85;

/**
 * 웹 전용: 사진을 긴 변 1024px 이하의 JPEG(0.85)로 다시 인코딩한 blob 을 만든다.
 * createImageBitmap, 없으면 Image + canvas 를 쓰고, 어느 단계든 실패하면 원본 blob 을 그대로 돌려준다(서버가 판단).
 * 비트맵·object URL·캔버스는 쓰자마자 해제한다.
 * @param {Blob} blob 고른 사진 원본
 * @returns {Promise<Blob>} 줄인 JPEG, 실패하면 원본
 */
export async function shrinkPhotoForWeb(blob) {
  let bitmap = null;
  let objectUrl = null;
  let canvas = null;
  try {
    let source;
    let width;
    let height;
    if (typeof createImageBitmap === "function") {
      bitmap = await createImageBitmap(blob);
      source = bitmap;
      width = bitmap.width;
      height = bitmap.height;
    } else {
      objectUrl = URL.createObjectURL(blob);
      const img = await new Promise((resolve, reject) => {
        const el = new Image();
        el.onload = () => resolve(el);
        el.onerror = () => reject(new Error("decode_failed"));
        el.src = objectUrl;
      });
      source = img;
      width = img.naturalWidth;
      height = img.naturalHeight;
    }
    if (!width || !height) return blob;
    const scale = Math.min(1, WEB_MAX_SIDE / Math.max(width, height));
    canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return blob;
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    const out = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", WEB_JPEG_QUALITY));
    return out ?? blob;
  } catch {
    return blob;
  } finally {
    bitmap?.close?.();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    if (canvas) {
      canvas.width = 0; // 캔버스 메모리 해제
      canvas.height = 0;
    }
  }
}
