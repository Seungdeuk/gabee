/** base64 글자를 바이트로 바꾼다(그림판이 PNG 를 base64 로 돌려준다). */
export function base64ToBytes(base64) {
  const binary = atob(String(base64).replace(/^data:[^,]*,/, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/**
 * 그림판이 만든 PNG(base64)를 앱 임시 폴더의 파일로 쓰고 올릴 수 있는 asset 으로 돌려준다.
 * 웹은 파일 시스템이 없어 Blob 으로 바로 올린다.
 * @param {string} base64
 * @returns {Promise<{ uri: string, file?: Blob }>}
 */
export async function pngAssetFromBase64(base64) {
  const bytes = base64ToBytes(base64);
  if (typeof document !== "undefined") return { uri: "draw.png", file: new Blob([bytes], { type: "image/png" }) };
  const { File, Paths } = await import("expo-file-system");
  const file = new File(Paths.cache, `gabee-draw-${Date.now()}.png`);
  file.create({ overwrite: true });
  file.write(bytes);
  return { uri: file.uri };
}

/**
 * multipart 폼에 파일 한 장을 'file' 로 붙인다. 웹은 Blob(asset.file, 없으면 asset.uri 를 받아서), 네이티브는 { uri, name, type } 으로 붙이고
 * Content-Type 은 fetch 가 boundary 와 함께 정한다(family-chat 의 사진 보내기와 같은 방식).
 * @param {FormData} form
 * @param {{ uri: string, file?: Blob }} asset
 * @param {string} name 파일 이름
 * @param {string} type 형식(image/png, image/jpeg …)
 */
export async function fileForUpload(form, asset, name, type) {
  if (asset.file) {
    form.append("file", asset.file, name);
  } else if (/^(blob|data):/.test(asset.uri)) {
    const blob = await (await fetch(asset.uri)).blob();
    form.append("file", blob, name);
  } else {
    form.append("file", { uri: asset.uri, name, type });
  }
}
