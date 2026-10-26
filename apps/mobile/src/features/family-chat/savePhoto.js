import { photoPath } from "@/shared/photoCache";

import { downloadPhoto, photoDownloadRequest } from "./api";

export const SAVE_FAIL_MESSAGE = "사진을 저장하지 못했어요";
export const SAVE_DONE_MESSAGE = "저장했어요";
export const SAVE_DENIED_MESSAGE = "사진 저장 권한이 필요해요. 설정에서 허용해 주세요";
export const SAVE_UNAVAILABLE_MESSAGE = "이 환경에서는 저장할 수 없어요";

/**
 * 권한 응답을 세 가지로 나눈다. granted: 저장 가능, denied: 거절(다시 물을 수 있음), blocked: 영구 거절(설정에서만 바꿀 수 있음).
 * @param {{ granted?: boolean, canAskAgain?: boolean } | null | undefined} response expo-media-library 의 PermissionResponse
 * @returns {"granted" | "denied" | "blocked"}
 */
export function permissionOutcome(response) {
  if (response?.granted) return "granted";
  return response?.canAskAgain === false ? "blocked" : "denied";
}

/**
 * 권한 결과에 맞는 안내 문구. 저장해도 되면 빈 문구.
 * @param {"granted" | "denied" | "blocked"} outcome
 * @returns {string}
 */
export function permissionMessage(outcome) {
  return outcome === "granted" ? "" : SAVE_DENIED_MESSAGE;
}

/**
 * 웹 또는 네이티브 중 어느 쪽으로 저장할지 고른다.
 * @param {string} os Platform.OS
 * @returns {"web" | "native"}
 */
export function saveTarget(os) {
  return os === "web" ? "web" : "native";
}

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
 * 네이티브 expo 모듈을 불러온다. 웹 번들에 섞이지 않도록 정적 import 대신 동적 import 를 쓴다. 불러오지 못하면 던진다.
 * @returns {Promise<{ MediaLibrary: object, FileSystem: object }>}
 */
export async function importNativeModules() {
  const [MediaLibrary, FileSystem] = await Promise.all([import("expo-media-library"), import("expo-file-system")]);
  return { MediaLibrary, FileSystem };
}

/**
 * 네이티브 의존성의 실제 구현(모듈은 주입할 수 있다). 새 객체형 expo-file-system API(File, Paths, File.downloadFileAsync)를 쓴다:
 * SDK 54 기본 진입점이고 헤더 전달·캐시 경로를 지원한다.
 * @param {{ MediaLibrary: object, FileSystem: object }} [modules] 시험용 가짜 모듈(없으면 importNativeModules)
 * @param {{ now?: () => number, random?: () => number }} [clock] 임시 파일 이름용 시각·난수(시험에서 고정한다)
 * @returns {Promise<{
 *   photoRequest: (path: string) => Promise<{ url: string, headers: Record<string, string> }>,
 *   getPermission: () => Promise<object>,
 *   requestPermission: () => Promise<object>,
 *   saveToLibrary: (uri: string) => Promise<void>,
 *   download: (url: string, headers: Record<string, string>, fileName: string) => Promise<{ fetch: () => Promise<string>, remove: () => void }>,
 * }>} savePhotoNative 가 받는 deps
 */
export async function loadNativeDeps(modules, clock = {}) {
  const { MediaLibrary, FileSystem } = modules ?? (await importNativeModules());
  const { File, Paths } = FileSystem;
  const now = clock.now ?? Date.now;
  const random = clock.random ?? Math.random;
  return {
    photoRequest: photoDownloadRequest,
    // 앨범에 쓰기만 하면 되므로 쓰기 전용 권한(writeOnly = true)만 요청한다
    getPermission: () => MediaLibrary.getPermissionsAsync(true),
    requestPermission: () => MediaLibrary.requestPermissionsAsync(true),
    // 앨범("가비")은 만들지 않는다: createAlbumAsync 는 라이브러리 읽기까지 요구해 권한 범위가 커진다
    saveToLibrary: (uri) => MediaLibrary.saveToLibraryAsync(uri),
    async download(url, headers, fileName) {
      // 작업마다 다른 임시 이름: 같은 사진을 동시에 저장해도 서로의 파일을 덮어쓰거나 지우지 않는다
      const tag = `${now().toString(36)}${Math.floor(random() * 36 ** 6).toString(36)}`;
      const target = new File(Paths.cache, `gabee-save-${tag}-${String(fileName).replace(/[^\w.-]/g, "")}`);
      return {
        async fetch() {
          const file = await File.downloadFileAsync(url, target, { headers, idempotent: true });
          return file.uri;
        },
        remove() {
          if (target.exists) target.delete();
        },
      };
    },
  };
}

/**
 * 네이티브 저장: 경로 검증 -> 권한 확인 -> (권한 뒤에) 인증 헤더를 만들어 캐시 파일에 받기 -> 사진 앱에 저장. 임시 파일은 성공·실패 모두 지운다.
 * 사진 경로·사용자 정보는 로그에 남기지 않는다.
 * @param {string} path 서버가 준 사진 경로
 * @param {string} fileName saveFileName 이 만든 이름
 * @param {object} [injected] 시험용 의존성(loadNativeDeps 가 돌려주는 모양, 없으면 loadNativeDeps)
 * @param {() => Promise<object>} [loader] 시험용: 의존성을 만드는 함수(기본 loadNativeDeps)
 * @returns {Promise<{ ok: boolean, message: string }>}
 */
export async function savePhotoNative(path, fileName, injected, loader = loadNativeDeps) {
  if (!photoPath(path)) return { ok: false, message: SAVE_FAIL_MESSAGE }; // 낯선 경로는 권한 창 전에 거절
  let deps = injected;
  if (!deps) {
    try {
      deps = await loader();
    } catch {
      return { ok: false, message: SAVE_UNAVAILABLE_MESSAGE }; // 모듈을 불러오지 못한 환경
    }
  }

  let outcome;
  try {
    outcome = permissionOutcome(await deps.getPermission());
    if (outcome === "denied") outcome = permissionOutcome(await deps.requestPermission());
  } catch {
    return { ok: false, message: SAVE_UNAVAILABLE_MESSAGE }; // 권한 API 가 없는 환경(예: Expo Go 제한)
  }
  if (outcome !== "granted") return { ok: false, message: permissionMessage(outcome) };

  let job;
  try {
    const request = await deps.photoRequest(path); // 인증 헤더는 권한을 받은 뒤 다운로드 직전에 만든다
    job = await deps.download(request.url, request.headers, fileName);
    const uri = await job.fetch();
    await deps.saveToLibrary(uri);
    return { ok: true, message: SAVE_DONE_MESSAGE };
  } catch {
    return { ok: false, message: SAVE_FAIL_MESSAGE };
  } finally {
    try {
      job?.remove();
    } catch {
      // 지우기 실패는 결과를 바꾸지 않는다(캐시 폴더는 시스템이 비운다)
    }
  }
}

/**
 * 사진을 기기에 저장한다. 웹은 내려받기, 네이티브는 사진 앱에 저장.
 * @param {{ url: string }} item 서버가 준 모음 항목(url 은 원본 경로)
 * @param {string} fileName saveFileName 이 만든 이름
 * @param {string} os Platform.OS ("web" 이면 내려받기)
 * @param {object} [nativeDeps] 시험용 네이티브 의존성
 * @returns {Promise<{ ok: boolean, message: string }>} message 는 화면에 보일 결과 문구
 */
export async function savePhoto(item, fileName, os, nativeDeps) {
  if (saveTarget(os) === "native") return savePhotoNative(item?.url, fileName, nativeDeps);
  try {
    await saveOnWeb(item.url, fileName);
    return { ok: true, message: SAVE_DONE_MESSAGE };
  } catch {
    return { ok: false, message: SAVE_FAIL_MESSAGE };
  }
}
