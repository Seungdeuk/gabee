/**
 * 채팅 문서 파일 열기·저장(expo-file-system, expo-sharing 을 쓰므로 순수 로직은 fileUtils.js).
 * 열기: 네이티브는 인증 헤더로 캐시에 받아 공유 시트(기기 앱으로 열기), 웹은 내려받기.
 * 저장: 안드로이드는 사용자가 먼저 폴더(드라이브 포함)를 고른 뒤 받아서 쓰고, 아이폰은 공유 시트의 "파일에 저장", 웹은 내려받기.
 * 파일 내용·이름·경로는 로그에 남기지 않는다.
 */
import { downloadFile, fileDownloadRequest } from "./api";
import {
  cacheDirName,
  chatFileMimeType,
  FILE_OPEN_FAIL,
  FILE_OPEN_UNAVAILABLE,
  fileSaveMode,
  fileSaveResult,
  isPickerCanceled,
  safeFileName,
  staleCacheDirs,
} from "./fileUtils";

/**
 * 네이티브 expo 모듈을 불러온다. 웹 번들에 섞이지 않도록 동적 import 를 쓴다. 불러오지 못하면 던진다.
 * @returns {Promise<{ FileSystem: object, Sharing: object }>}
 */
async function importNativeModules() {
  const [FileSystem, Sharing] = await Promise.all([import("expo-file-system"), import("expo-sharing")]);
  return { FileSystem, Sharing };
}

/**
 * 웹: 로그인 헤더로 받은 blob 을 a 태그 download 로 내려받는다.
 * @param {string} path attachment.url
 * @param {string} name 저장할 이름
 * @returns {Promise<void>}
 */
async function downloadOnWeb(path, name) {
  const blob = await downloadFile(path);
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
}

/**
 * 하루 넘은 임시 폴더를 지운다. 공유 시트·열린 앱이 읽는 동안에는 지울 수 없어서 다음에 열거나 저장할 때 정리한다. 실패해도 무시한다.
 * @param {object} FileSystem expo-file-system
 */
function cleanStaleCache(FileSystem) {
  try {
    const { Directory, Paths } = FileSystem;
    const entries = new Directory(Paths.cache).list();
    const nameOf = (entry) => decodeURIComponent(String(entry.uri).replace(/\/+$/, "").split("/").pop() ?? "");
    const stale = new Set(staleCacheDirs(entries.map(nameOf), Date.now()));
    for (const entry of entries) {
      if (stale.has(nameOf(entry))) entry.delete();
    }
  } catch {
    // 무시
  }
}

/**
 * 인증 헤더로 캐시에 받는다. 작업마다 고유한 하위 폴더(gabee-file-<시각>-<난수>/) 안에 원래 파일명(한글 보존, 경로 문자만 치환)으로 저장한다.
 * @param {object} FileSystem expo-file-system
 * @param {{ url: string, filename?: string | null }} attachment
 * @returns {Promise<object>} 받은 File
 */
async function downloadToCache(FileSystem, attachment) {
  const { Directory, File, Paths } = FileSystem;
  const request = await fileDownloadRequest(attachment.url);
  const dir = new Directory(Paths.cache, cacheDirName(Date.now(), Math.random()));
  dir.create({ idempotent: true, intermediates: true });
  const target = new File(dir, safeFileName(attachment.filename));
  return File.downloadFileAsync(request.url, target, { headers: request.headers, idempotent: true });
}

/**
 * 공유 시트로 파일을 연다(기기의 다른 앱으로 열기·공유).
 * @param {object} Sharing expo-sharing
 * @param {object} file 받은 File
 * @param {{ filename?: string | null, content_type?: string | null }} attachment
 * @returns {Promise<boolean>} 공유할 수 없는 환경이면 false
 */
async function shareFile(Sharing, file, attachment) {
  if (!(await Sharing.isAvailableAsync())) return false;
  await Sharing.shareAsync(file.uri, { mimeType: attachment.content_type || chatFileMimeType({ name: attachment.filename }), dialogTitle: safeFileName(attachment.filename) });
  return true;
}

/**
 * 파일 말풍선을 눌렀을 때: 열기/공유. 임시 파일은 열린 앱이 읽을 수 있게 지우지 않고 다음에 정리한다.
 * @param {{ url: string, filename?: string | null, content_type?: string | null }} attachment
 * @param {string} os Platform.OS
 * @returns {Promise<{ ok: boolean, message: string }>} 실패했을 때만 message 를 화면에 보인다
 */
export async function openChatFile(attachment, os) {
  if (os === "web") {
    try {
      await downloadOnWeb(attachment.url, safeFileName(attachment.filename));
      return { ok: true, message: "" };
    } catch {
      return { ok: false, message: FILE_OPEN_FAIL };
    }
  }
  let modules;
  try {
    modules = await importNativeModules();
  } catch {
    return { ok: false, message: FILE_OPEN_UNAVAILABLE };
  }
  cleanStaleCache(modules.FileSystem);
  try {
    const file = await downloadToCache(modules.FileSystem, attachment);
    const shared = await shareFile(modules.Sharing, file, attachment);
    return shared ? { ok: true, message: "" } : { ok: false, message: FILE_OPEN_UNAVAILABLE };
  } catch {
    return { ok: false, message: FILE_OPEN_FAIL };
  }
}

/**
 * 안드로이드: 받은 파일을 이미 고른 폴더(드라이브 포함)에 쓴다.
 * @param {object} directory 사용자가 고른 Directory
 * @param {object} cached 캐시에 받은 File
 * @param {{ filename?: string | null, content_type?: string | null }} attachment
 */
async function writeToFolder(directory, cached, attachment) {
  const name = safeFileName(attachment.filename);
  const target = directory.createFile(name, attachment.content_type || chatFileMimeType({ name }));
  target.write(await cached.bytes());
}

/**
 * 문서를 기기의 "내 파일/드라이브"에 저장한다. 안드로이드는 저장 위치(폴더, 드라이브 포함)를 먼저 고르고(취소하면 받지 않는다) 받아서 쓰며,
 * 폴더에 쓰지 못하면 공유 시트로 대신한다. 아이폰은 공유 시트의 "파일에 저장", 웹은 내려받기. 임시 폴더는 바로 지우지 않고 하루가 지나면 다음 열기·저장 때 정리한다.
 * 사진첩 저장은 savePhoto.js 가 맡는다.
 * @param {{ url: string, filename?: string | null, content_type?: string | null }} attachment
 * @param {string} os Platform.OS
 * @returns {Promise<{ ok: boolean, message: string }>}
 */
export async function saveChatFile(attachment, os) {
  const mode = fileSaveMode(os);
  if (mode === "web") {
    try {
      await downloadOnWeb(attachment.url, safeFileName(attachment.filename));
      return fileSaveResult("done");
    } catch {
      return fileSaveResult("failed");
    }
  }
  let modules;
  try {
    modules = await importNativeModules();
  } catch {
    return fileSaveResult("unavailable");
  }
  const { FileSystem, Sharing } = modules;
  cleanStaleCache(FileSystem);

  let directory = null;
  if (mode === "folder") {
    try {
      directory = await FileSystem.Directory.pickDirectoryAsync(); // 받기 전에 먼저 고른다: 취소하면 헛다운로드가 없다
    } catch (e) {
      if (isPickerCanceled(e)) return fileSaveResult("canceled");
      directory = null; // 폴더 선택을 쓸 수 없으면 공유 시트로 대신한다
    }
  }

  try {
    const cached = await downloadToCache(FileSystem, attachment);
    if (directory) {
      try {
        await writeToFolder(directory, cached, attachment);
        return fileSaveResult("done");
      } catch {
        // 폴더에 쓰지 못하면 공유 시트로 대신한다
      }
    }
    return fileSaveResult((await shareFile(Sharing, cached, attachment)) ? "done" : "unavailable");
  } catch {
    return fileSaveResult("failed");
  }
}
