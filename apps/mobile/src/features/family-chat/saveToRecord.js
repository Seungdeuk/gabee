import { photoPath } from "@/shared/photoCache";

import { downloadPhoto, uploadToAssistantRecord } from "./api";
import { loadNativeDeps } from "./savePhoto";

export const RECORD_DONE_MESSAGE = "가비 기록에 저장했어요. 읽는 데 잠시 걸릴 수 있어요";
export const RECORD_FAIL_MESSAGE = "가비 기록에 저장하지 못했어요";
export const RECORD_UNAVAILABLE_MESSAGE = "이 환경에서는 저장할 수 없어요";
export const RECORD_BUTTON_LABEL = "가비 기록에 저장";

/**
 * "가비 기록에 저장" 버튼을 보일 사진인가: 가족 전체방의 사진 메시지만. 1:1 방의 사진은 가족 전체가 보는 기록으로 옮기지 않는다
 * (기록은 가족 그룹 단위로만 나뉘어 있어 한번 저장되면 가족 누구나 볼 수 있다).
 * @param {{ direct: boolean, attachment?: { url?: string } | null }} options direct 는 1:1 방인지
 * @returns {boolean}
 */
export function canSaveToRecord({ direct, attachment }) {
  return !direct && Boolean(attachment?.url);
}

/**
 * 기록으로 올릴 때 쓰는 파일 이름: gabee-chat-<사진 id 앞부분>.jpg (서버가 채팅 사진을 항상 JPEG 으로 다시 만든다).
 * @param {{ id?: string } | null | undefined} attachment
 * @returns {string}
 */
export function recordFileName(attachment) {
  const id = String(attachment?.id ?? "").replace(/[^\w]/g, "").slice(0, 12);
  return `gabee-chat-${id || "photo"}.jpg`;
}

/**
 * 웹은 받은 blob 을 그대로, 네이티브는 캐시 파일을 올린다.
 * @param {string} os Platform.OS
 * @returns {"web" | "native"}
 */
export function recordTarget(os) {
  return os === "web" ? "web" : "native";
}

/**
 * 웹: 로그인 헤더로 받은 blob 을 multipart 'file' 로 올린다.
 * @param {string} path 서버가 준 사진 경로
 * @param {string} fileName
 * @param {{ download?: (path: string) => Promise<Blob>, upload?: (form: FormData) => Promise<unknown> }} deps 시험용
 */
async function saveOnWeb(path, fileName, deps) {
  const blob = await (deps.download ?? downloadPhoto)(path);
  const form = new FormData();
  form.append("file", blob, fileName);
  await (deps.upload ?? uploadToAssistantRecord)(form);
}

/**
 * 네이티브: 사진을 캐시 파일로 받은 뒤({uri,name,type}) 올리고, 임시 파일은 성공·실패 모두 지운다.
 * @param {string} path 서버가 준 사진 경로
 * @param {string} fileName
 * @param {{ native?: object, upload?: (form: FormData) => Promise<unknown>, loader?: () => Promise<object> }} deps 시험용
 * @returns {Promise<{ ok: boolean, message: string }>}
 */
async function saveOnNative(path, fileName, deps) {
  let native = deps.native;
  if (!native) {
    try {
      native = await (deps.loader ?? loadNativeDeps)();
    } catch {
      return { ok: false, message: RECORD_UNAVAILABLE_MESSAGE }; // 파일 시스템 모듈을 불러오지 못한 환경
    }
  }
  let job;
  try {
    const request = await native.photoRequest(path);
    job = await native.download(request.url, request.headers, fileName);
    const uri = await job.fetch();
    const form = new FormData();
    form.append("file", { uri, name: fileName, type: "image/jpeg" });
    await (deps.upload ?? uploadToAssistantRecord)(form);
    return { ok: true, message: RECORD_DONE_MESSAGE };
  } catch {
    return { ok: false, message: RECORD_FAIL_MESSAGE };
  } finally {
    try {
      job?.remove();
    } catch {
      // 지우기 실패는 결과를 바꾸지 않는다(캐시 폴더는 시스템이 비운다)
    }
  }
}

/**
 * 채팅 사진 한 장을 AI 비서의 가족 기록으로 올린다(기존 파일 올리기 `POST /ai-assistant/files` 를 그대로 쓴다: 서버가 원본 보관 -> 글자 읽기 ->
 * 개인정보 가리기 -> 분류 -> 저장을 응답 뒤 백그라운드로 한다). 사진 경로·사용자 정보는 로그에 남기지 않는다.
 * @param {{ id?: string, url?: string } | null | undefined} attachment 메시지의 attachment(url 은 서버가 준 원본 경로)
 * @param {string} os Platform.OS
 * @param {object} [deps] 시험용 의존성(download·upload·native·loader)
 * @returns {Promise<{ ok: boolean, message: string }>} message 는 화면에 보일 결과 문구
 */
export async function saveToRecord(attachment, os, deps = {}) {
  const path = attachment?.url;
  if (!photoPath(path)) return { ok: false, message: RECORD_FAIL_MESSAGE }; // 낯선 경로는 내려받기 전에 거절
  const fileName = recordFileName(attachment);
  if (recordTarget(os) === "native") return saveOnNative(path, fileName, deps);
  try {
    await saveOnWeb(path, fileName, deps);
    return { ok: true, message: RECORD_DONE_MESSAGE };
  } catch {
    return { ok: false, message: RECORD_FAIL_MESSAGE };
  }
}
