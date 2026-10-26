/**
 * 웹 전용 이미지 줄이기(공용). 올리기 전에 긴 변을 maxSide 이하로, JPEG 로 다시 인코딩한다.
 */

/**
 * 웹 전용: 사진을 긴 변 maxSide 이하의 JPEG 로 다시 인코딩한 blob 을 만든다.
 * createImageBitmap, 없으면 Image + canvas 를 쓰고, 어느 단계든 실패하면 원본 blob 을 그대로 돌려준다(서버가 판단).
 * 비트맵·object URL·캔버스는 쓰자마자 해제한다.
 * @param {Blob} blob 고른 사진 원본
 * @param {{ maxSide: number, quality: number }} options 긴 변 한도(px)와 JPEG 품질(0~1)
 * @returns {Promise<Blob>} 줄인 JPEG, 실패하면 원본
 */
export async function shrinkImageForWeb(blob, { maxSide, quality }) {
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
    const scale = Math.min(1, maxSide / Math.max(width, height));
    canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) return blob;
    ctx.fillStyle = "#ffffff"; // 투명한 PNG 가 JPEG 로 바뀔 때 검게 되지 않도록 흰 바탕을 먼저 칠한다
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    const out = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
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
