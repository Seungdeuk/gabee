// 보낸 부탁의 "메모 바꾸기" 시트 규칙과 저장 실패 문구. 화면에 의존하지 않아 node 테스트로 확인한다.

/** 서버 메모 최대 길이(글자 수, 코드 포인트 기준). docs/contracts/openapi.json 의 memo 와 맞춘다. */
export const REQUEST_MEMO_MAX = 2000;

/** 글자 수(이모지 등 한 글자가 두 단위인 것도 한 글자로 센다). */
export const memoChars = (text) => [...String(text ?? "")].length;

/**
 * 고친 메모(draft)에 따른 안내 문구와 저장 가능 여부. 2000자를 넘거나 바뀐 게 없으면 저장할 수 없다.
 * 저장할 값은 앞뒤 공백을 뗀 값이다(빈 값이면 메모를 지운다).
 * @param {string} current 지금 저장된 메모
 * @param {string} draft 시트에서 쓴 메모
 * @returns {{ message: string | null, canSave: boolean }}
 */
export function memoGuide(current, draft) {
  const value = String(draft ?? "").trim();
  if (memoChars(value) > REQUEST_MEMO_MAX) return { message: `메모는 ${REQUEST_MEMO_MAX}자까지 쓸 수 있어요`, canSave: false };
  const unchanged = value === String(current ?? "").trim();
  if (unchanged) return { message: null, canSave: false };
  if (value === "") return { message: "메모를 비우면 메모가 지워져요", canSave: true };
  return { message: null, canSave: true };
}

/**
 * 메모 저장 실패를 안내 문구로 바꾼다. 서버 오류(ApiError)의 status·code 를 보고, 모르는 오류는 일반 문구를 쓴다.
 * 403 not_owner: 보낸 사람만 고칠 수 있다. 400 request_canceled: 취소된 부탁. 422: 글자 수 초과.
 * @param {unknown} error
 * @returns {string}
 */
export function memoErrorMessage(error) {
  const status = error?.status;
  const code = error?.code;
  if (status === 403 || code === "not_owner") return "보낸 사람만 메모를 고칠 수 있어요";
  if (code === "request_canceled") return "취소된 부탁은 메모를 고칠 수 없어요";
  if (status === 422) return `메모는 ${REQUEST_MEMO_MAX}자까지 쓸 수 있어요`;
  return "메모를 바꾸지 못했어요. 잠시 뒤 다시 해 주세요";
}
