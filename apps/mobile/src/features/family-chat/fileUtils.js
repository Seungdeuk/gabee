/**
 * 채팅 문서 파일 첨부의 순수 로직(화면·네트워크와 무관): 허용 형식·크기 검사, 크기 문구, "+" 메뉴 항목, 저장 안내 문구.
 * 서버(POST /family-chat/files)도 같은 한도를 다시 검사한다. 파일 내용·이름은 어디에도 기록하지 않는다.
 */
import { roomErrorMessage } from "./chatUtils";

/** 서버가 받는 한도(20MB). */
export const MAX_CHAT_FILE_BYTES = 20 * 1024 * 1024;

/** 보낼 수 있는 문서 확장자. */
export const FILE_EXTENSIONS = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "hwp", "hwpx", "txt", "csv"];

const MIME_BY_EXT = {
  pdf: "application/pdf",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xls: "application/vnd.ms-excel",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ppt: "application/vnd.ms-powerpoint",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  hwp: "application/x-hwp",
  hwpx: "application/vnd.hancom.hwpx",
  txt: "text/plain",
  csv: "text/csv",
};

export const FILE_TYPE_MESSAGE = "PDF, 워드, 엑셀, 파워포인트, 한글, 텍스트, CSV 파일만 보낼 수 있어요";
export const FILE_TOO_LARGE_MESSAGE = "파일은 20MB까지 보낼 수 있어요";
export const FILE_EMPTY_MESSAGE = "빈 파일은 보낼 수 없어요";
export const FILE_SEND_FAIL_MESSAGE = "파일을 보내지 못했어요. 잠시 후 다시 시도해 주세요";
export const FILE_INVALID_MESSAGE = "지원하지 않는 파일이거나 내용이 맞지 않아요";
export const FILE_BUSY_MESSAGE = "지금 파일을 처리하는 중이 많아요. 잠시 후 다시 해 주세요";
export const FILE_PREVIEW_TEXT = "파일";

/** "+" 메뉴(아래에서 올라오는 시트) 항목. 사진·파일은 바로 선택 화면을 열고, 나머지(일정·정산·안부)는 실제 기능이 이후 작업이라 누르면 준비 중 안내만 한다. */
export const PLUS_MENU_ITEMS = [
  { key: "photo", label: "사진", icon: "image-outline" },
  { key: "file", label: "파일", icon: "document-attach-outline" },
  { key: "schedule", label: "일정", icon: "calendar-outline" },
  { key: "settle", label: "정산", icon: "wallet-outline" },
  { key: "safety", label: "안부", icon: "heart-outline" },
];
/**
 * "+" 메뉴 항목이 사진 보내기인지(나머지는 준비 중 안내).
 * @param {string} key
 * @returns {boolean}
 */
export const isPlusPhoto = (key) => key === "photo";
/**
 * "+" 메뉴 항목이 파일(문서) 보내기인지.
 * @param {string} key
 * @returns {boolean}
 */
export const isPlusFile = (key) => key === "file";
/**
 * "+" 메뉴 항목이 공유 카드(일정·정산) 보내기인지.
 * @param {string} key
 * @returns {boolean}
 */
export const isPlusShare = (key) => key === "schedule" || key === "settle";
/**
 * 공유 항목이 서버에 보낼 카드 종류(일정 → "event", 정산 → "settlement"). 공유 항목이 아니면 null.
 * @param {string} key
 * @returns {"event" | "settlement" | null}
 */
export const plusShareKind = (key) => (key === "schedule" ? "event" : key === "settle" ? "settlement" : null);
export const PLUS_SOON_NOTICE = "준비 중이에요";
export const PLUS_SOON_MS = 3000; // 안내가 저절로 사라지는 시간

/**
 * 파일 이름의 확장자(소문자, 점 없음). 없으면 빈 문자열.
 * @param {string | null | undefined} name
 * @returns {string}
 */
export const fileExtOf = (name) => /\.([a-z0-9]+)$/i.exec(String(name ?? "").trim())?.[1]?.toLowerCase() ?? "";

/**
 * 올릴 파일의 형식. 확장자로 정하고 모르면 asset 의 mimeType, 그것도 없으면 일반 바이너리.
 * @param {{ name?: string | null, mimeType?: string | null }} asset
 * @returns {string}
 */
export const chatFileMimeType = (asset) => MIME_BY_EXT[fileExtOf(asset?.name)] ?? (asset?.mimeType || "application/octet-stream");

/**
 * 고른 파일을 올려도 되는지 앱에서 먼저 검사한다(서버도 다시 검사). 크기를 모르면 크기 검사는 서버에 맡긴다.
 * @param {{ name?: string | null, size?: number | null }} asset expo-document-picker 의 asset
 * @returns {{ ok: true } | { ok: false, code: "unsupported_file_type" | "file_too_large" | "file_empty", message: string }}
 */
export function validateChatFile(asset) {
  if (!FILE_EXTENSIONS.includes(fileExtOf(asset?.name))) return { ok: false, code: "unsupported_file_type", message: FILE_TYPE_MESSAGE };
  if (typeof asset?.size === "number" && asset.size > MAX_CHAT_FILE_BYTES) return { ok: false, code: "file_too_large", message: FILE_TOO_LARGE_MESSAGE };
  if (typeof asset?.size === "number" && asset.size <= 0) return { ok: false, code: "file_empty", message: FILE_EMPTY_MESSAGE };
  return { ok: true };
}

/**
 * 파일 크기 문구: 1KB 미만은 "512B", 1MB 미만은 "340KB", 그 이상은 소수 한 자리 "1.2MB". 모르면 빈 문구.
 * @param {number | null | undefined} bytes
 * @returns {string}
 */
export function formatFileSize(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${Math.round(bytes)}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

/**
 * 파일 첨부 메시지인지(kind 가 "file"). kind 가 없거나 "image" 면 사진(하위 호환).
 * @param {{ attachment?: { kind?: string } | null } | null | undefined} message
 * @returns {boolean}
 */
export const isFileMessage = (message) => message?.attachment?.kind === "file";

/**
 * 파일 보내기 오류를 사용자 문장으로(코드가 없어도 413/415/429 상태로 알아본다).
 * @param {{ code?: string, status?: number } | null | undefined} error
 * @returns {string}
 */
export function fileSendErrorMessage(error) {
  if (error?.code === "file_too_large" || error?.status === 413) return FILE_TOO_LARGE_MESSAGE;
  if (error?.code === "invalid_file") {
    const detail = typeof error.message === "string" ? error.message.trim() : ""; // 서버가 준 구체적인 안내(확장자·내용 불일치, 빈 파일 등)
    return detail && detail !== "invalid_file" ? detail : FILE_INVALID_MESSAGE;
  }
  if (error?.code === "file_busy") return FILE_BUSY_MESSAGE;
  if (error?.code === "file_failed") return FILE_SEND_FAIL_MESSAGE;
  if (error?.code === "unsupported_file_type" || error?.status === 415) return FILE_TYPE_MESSAGE;
  if (error?.code === "file_empty") return FILE_EMPTY_MESSAGE;
  if (error?.status === 429) return "파일을 너무 자주 보냈어요. 잠시 후 다시 해 주세요";
  if (error?.code || error?.status) return roomErrorMessage(error);
  return FILE_SEND_FAIL_MESSAGE;
}

// ---------------------------------------------------------------------------------------------
// 저장 안내: 사진은 사진첩(갤러리), 문서는 내 파일/드라이브(사용자가 저장 위치를 고른다)

export const PHOTO_SAVE_LABEL = "사진첩에 저장";
export const FILE_SAVE_LABEL = "내 파일/드라이브에 저장";
export const FILE_SAVE_HELP = "저장할 위치를 선택해 주세요. 드라이브에 저장하려면 위치에서 드라이브를 고르세요";
export const FILE_SAVE_DONE = "저장했어요";
export const FILE_SAVE_FAIL = "파일을 저장하지 못했어요";
export const FILE_SAVE_CANCELED = "저장을 취소했어요";
export const FILE_SAVE_UNAVAILABLE = "이 환경에서는 저장할 수 없어요";
export const FILE_OPEN_FAIL = "파일을 열지 못했어요";
export const FILE_OPEN_UNAVAILABLE = "이 환경에서는 파일을 열 수 없어요";

/**
 * 문서 저장 방식: 안드로이드는 폴더 선택(드라이브 포함), 아이폰은 공유 시트의 "파일에 저장", 웹은 내려받기.
 * @param {string} os Platform.OS
 * @returns {"web" | "folder" | "share"}
 */
export const fileSaveMode = (os) => (os === "web" ? "web" : os === "android" ? "folder" : "share");

/**
 * 저장 직전에 보일 짧은 도움말(웹은 브라우저가 알아서 하므로 없다).
 * @param {string} os Platform.OS
 * @returns {string}
 */
export const fileSaveHelp = (os) => (fileSaveMode(os) === "web" ? "" : FILE_SAVE_HELP);

/**
 * 저장 결과를 사용자 문구로. 사용자가 위치 선택을 취소했으면 오류가 아니라 취소 안내.
 * @param {"done" | "canceled" | "unavailable" | "failed"} outcome
 * @returns {{ ok: boolean, message: string }}
 */
export function fileSaveResult(outcome) {
  if (outcome === "done") return { ok: true, message: FILE_SAVE_DONE };
  if (outcome === "canceled") return { ok: false, message: FILE_SAVE_CANCELED };
  if (outcome === "unavailable") return { ok: false, message: FILE_SAVE_UNAVAILABLE };
  return { ok: false, message: FILE_SAVE_FAIL };
}

/** 사용자가 위치 선택을 취소한 오류인지(expo-file-system 코드 ERR_PICKER_CANCELLED 를 먼저, 문구는 보조로 본다). */
export const isPickerCanceled = (error) => error?.code === "ERR_PICKER_CANCELLED" || /cancel/i.test(String(error?.message ?? ""));

/** 받은 파일을 두는 임시 폴더 이름 접두어. 폴더마다 시각이 들어 있어 오래된 것을 알아볼 수 있다. */
export const CACHE_DIR_PREFIX = "gabee-file-";
export const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * 임시 폴더 이름: `gabee-file-<시각(36진수)>-<난수>`. 안에는 원래 파일명 그대로 저장한다(한글 보존).
 * @param {number} now Date.now()
 * @param {number} random 0~1 난수
 * @returns {string}
 */
export const cacheDirName = (now, random) => `${CACHE_DIR_PREFIX}${Math.floor(now).toString(36)}-${Math.floor(random * 36 ** 6).toString(36)}`;

/**
 * 임시 폴더 이름 중 하루 넘은 것(오래된 것). 이름을 읽을 수 없는 것은 건드리지 않는다.
 * @param {string[]} names 캐시 폴더 안의 이름들
 * @param {number} now Date.now()
 * @param {number} [maxAge] 밀리초
 * @returns {string[]}
 */
export function staleCacheDirs(names, now, maxAge = CACHE_MAX_AGE_MS) {
  return names.filter((name) => {
    const m = new RegExp(`^${CACHE_DIR_PREFIX}([0-9a-z]+)-[0-9a-z]+$`).exec(name);
    if (!m) return false;
    const at = parseInt(m[1], 36);
    return Number.isFinite(at) && now - at >= maxAge;
  });
}

/**
 * 저장에 쓸 안전한 파일 이름(경로 문자 제거). 비면 "file".
 * @param {string | null | undefined} name
 * @returns {string}
 */
export const safeFileName = (name) => String(name ?? "").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").trim().slice(0, 120) || "file";
