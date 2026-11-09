import { savePhotoToLibrary } from "./api";
import { chatErrorMessage } from "./messages";

export const LIBRARY_BUTTON_LABEL = "문서로 저장";
export const LIBRARY_SAVING_LABEL = "저장하는 중…";
export const LIBRARY_QUEUED_MESSAGE = "문서함에 저장을 시작했어요. 글을 읽는 데 시간이 걸리고, 처방전·신분증 같은 민감한 문서는 저장하지 않아요";
export const LIBRARY_DONE_LABEL = "저장 요청했어요";
export const LIBRARY_ALREADY_MESSAGE = "이미 가족 문서함에 있어요";
export const LIBRARY_FAIL_MESSAGE = "문서함에 저장하지 못했어요";

/**
 * "문서로 저장" 버튼을 보일 사진인가: 가족 전체방의 사진 메시지만(1:1 방의 사진은 가족 공유 문서함으로 옮기지 않는다).
 * @param {{ direct: boolean, attachment?: { id?: string, url?: string } | null }} options direct 는 1:1 방인지
 * @returns {boolean}
 */
export function canSaveToLibrary({ direct, attachment }) {
  return !direct && Boolean(attachment?.id) && Boolean(attachment?.url);
}

/**
 * 채팅 사진 한 장을 가족 공유 문서함에 직접 넣는다(`POST /family-chat/photos/{id}/library`). 오류는 던지지 않고 문구로 바꾼다.
 * @param {{ id?: string } | null | undefined} attachment 메시지의 attachment
 * @param {{ save?: (attachmentId: string) => Promise<{ status: "queued" | "already" }> }} [deps] 시험용
 * @returns {Promise<{ ok: boolean, message: string }>} message 는 화면에 보일 결과 문구
 */
export async function saveToLibrary(attachment, deps = {}) {
  if (!attachment?.id) return { ok: false, message: LIBRARY_FAIL_MESSAGE };
  try {
    const result = await (deps.save ?? savePhotoToLibrary)(attachment.id);
    return { ok: true, message: result?.status === "already" ? LIBRARY_ALREADY_MESSAGE : LIBRARY_QUEUED_MESSAGE };
  } catch (e) {
    return { ok: false, message: chatErrorMessage(e) || LIBRARY_FAIL_MESSAGE };
  }
}
