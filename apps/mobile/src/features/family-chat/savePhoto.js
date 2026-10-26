import { downloadPhoto } from "./api";

export const SAVE_SOON_MESSAGE = "이 기기에서는 곧 지원돼요";
export const SAVE_FAIL_MESSAGE = "사진을 저장하지 못했어요";

/**
 * 웹: 로그인 헤더로 받은 blob 을 a 태그 download 로 내려받는다.
 * @param {string} path 서버가 준 사진 경로
 * @param {string} fileName
 * @returns {Promise<void>}
 */
async function saveOnWeb(path, fileName) {
  const blob = await downloadPhoto(path);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
}

/**
 * 네이티브 저장 자리. expo-file-system 사용이 승인되면 여기서 사진을 캐시 파일로 받고 expo-media-library 로 앨범에 저장한다.
 * 지금은 안내만 한다(두 패키지 모두 import 하지 않는다).
 * @returns {Promise<{ ok: false, message: string }>}
 */
async function saveOnNative() {
  // TODO(expo-file-system 승인 후): FileSystem.downloadAsync(원본, 캐시 경로, { headers: authHeaders() }) -> MediaLibrary.saveToLibraryAsync
  return { ok: false, message: SAVE_SOON_MESSAGE };
}

/**
 * 사진을 기기에 저장한다. 플랫폼별로 나뉜다: 웹은 내려받기, 네이티브는 아직 안내만.
 * @param {{ url: string }} item 서버가 준 모음 항목(url 은 원본 경로)
 * @param {string} fileName saveFileName 이 만든 이름
 * @param {string} os Platform.OS ("web" 이면 내려받기)
 * @returns {Promise<{ ok: boolean, message: string }>} message 는 화면에 보일 결과 문구
 */
export async function savePhoto(item, fileName, os) {
  if (os !== "web") return saveOnNative();
  try {
    await saveOnWeb(item.url, fileName);
    return { ok: true, message: "저장했어요" };
  } catch {
    return { ok: false, message: SAVE_FAIL_MESSAGE };
  }
}
