/**
 * 설정 탭의 상태 점검 문구(순수 함수). 베타 폰에서 위치가 왜 안 쌓이는지 바로 알 수 있게 한다.
 */

/**
 * 위치 권한 상태를 사람이 읽는 말로.
 * @param {"granted" | "denied" | "undetermined" | string} foreground 앞 권한(앱을 쓰는 동안)
 * @param {"granted" | "denied" | "undetermined" | string} background 뒤 권한(항상 허용)
 * @returns {{ ok: boolean, text: string }}
 */
export function describePermission(foreground, background) {
  if (foreground !== "granted") return { ok: false, text: "꺼져 있어요. 휴대폰 설정에서 위치를 허용해 주세요" };
  if (background !== "granted") return { ok: false, text: "앱을 쓰는 동안만 허용돼 있어요. 앱을 끄면 위치가 모이지 않아요('항상 허용'으로 바꿔 주세요)" };
  return { ok: true, text: "항상 허용" };
}

/**
 * 서버가 마지막으로 받은 내 위치가 얼마나 전인지.
 * @param {string | null | undefined} recordedIso 내 마지막 위치를 잰 시각
 * @param {number} [now] 현재 시각(ms), 시험용
 * @returns {{ ok: boolean, text: string }}
 */
export function describeLastSent(recordedIso, now = Date.now()) {
  if (!recordedIso) return { ok: false, text: "아직 서버에 쌓인 위치가 없어요" };
  const minutes = Math.max(0, Math.round((now - new Date(recordedIso).getTime()) / 60000));
  if (minutes < 1) return { ok: true, text: "방금" };
  if (minutes < 60) return { ok: minutes <= 15, text: `${minutes}분 전` };
  const hours = Math.round(minutes / 60);
  return { ok: false, text: hours < 24 ? `${hours}시간 전` : "하루 넘게 전" };
}
