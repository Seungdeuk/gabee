import { removePhotoFromLibrary, savePhotoToLibrary } from "./api";
import { chatErrorMessage } from "./messages";

export const LIBRARY_BUTTON_LABEL = "문서로 저장";
export const LIBRARY_SAVING_LABEL = "저장하는 중…";
export const LIBRARY_QUEUED_MESSAGE = "문서함에 저장을 시작했어요. 글을 읽는 데 시간이 걸려요. 가족 모두가 볼 수 있어요";
export const LIBRARY_DONE_LABEL = "저장 요청했어요";
export const LIBRARY_ALREADY_MESSAGE = "이미 가족 문서함에 있어요";
export const LIBRARY_FAIL_MESSAGE = "문서함에 저장하지 못했어요";

export const LIBRARY_REMOVE_LABEL = "문서함에서 빼기";
export const LIBRARY_REMOVE_CONFIRM_LABEL = "한 번 더 누르면 빠져요";
export const LIBRARY_REMOVING_LABEL = "빼는 중…";
export const LIBRARY_REMOVED_LABEL = "문서함에서 뺐어요";
export const LIBRARY_REMOVED_MESSAGE = "문서함에서 뺐어요. 채팅 사진은 그대로예요";
export const LIBRARY_REMOVE_FAIL_MESSAGE = "문서함에서 빼지 못했어요";

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

/**
 * 채팅 사진에서 만든 문서함 기록을 뺀다(`DELETE /family-chat/photos/{id}/library`, T09). 채팅 사진은 그대로다. 오류는 던지지 않고 문구로 바꾼다.
 * 이미 문서함에 없으면(409 not_in_library) 결과가 같으므로 성공으로 본다.
 * @param {{ id?: string } | null | undefined} attachment 메시지의 attachment
 * @param {{ remove?: (attachmentId: string) => Promise<unknown> }} [deps] 시험용
 * @returns {Promise<{ ok: boolean, message: string }>} message 는 화면에 보일 결과 문구
 */
export async function removeFromLibrary(attachment, deps = {}) {
  if (!attachment?.id) return { ok: false, message: LIBRARY_REMOVE_FAIL_MESSAGE };
  try {
    await (deps.remove ?? removePhotoFromLibrary)(attachment.id);
    return { ok: true, message: LIBRARY_REMOVED_MESSAGE };
  } catch (e) {
    if (e?.code === "not_in_library") return { ok: true, message: LIBRARY_REMOVED_MESSAGE };
    return { ok: false, message: chatErrorMessage(e) || LIBRARY_REMOVE_FAIL_MESSAGE };
  }
}

/**
 * "문서함에서 빼기" 버튼을 눌렀을 때 할 일. 실수로 지우지 않게 처음 누르면 확인 단계로만 바뀌고, 확인 단계에서 다시 누르면 실제로 뺀다.
 * @param {{ confirming?: boolean, removing?: boolean, removed?: boolean }} state 지금 상태
 * @returns {"confirm" | "remove" | "ignore"} confirm 은 확인 단계로, remove 는 요청 보내기, ignore 는 아무것도 하지 않음(진행 중·이미 뺌)
 */
export function nextRemoveStep({ confirming = false, removing = false, removed = false } = {}) {
  if (removing || removed) return "ignore";
  return confirming ? "remove" : "confirm";
}

/**
 * "문서함에서 빼기" 버튼 문구.
 * @param {{ confirming?: boolean, removing?: boolean, removed?: boolean }} state 지금 상태
 * @returns {string}
 */
export function removeLabel({ confirming = false, removing = false, removed = false } = {}) {
  if (removing) return LIBRARY_REMOVING_LABEL;
  if (removed) return LIBRARY_REMOVED_LABEL;
  return confirming ? LIBRARY_REMOVE_CONFIRM_LABEL : LIBRARY_REMOVE_LABEL;
}
