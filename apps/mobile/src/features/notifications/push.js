/** 서버가 푸시를 보낼 때 쓰는 안드로이드 알림 채널 id(서버 app/shared/push.py 의 ANDROID_CHANNEL_ID 와 같다). */
export const PUSH_CHANNEL_ID = "default";

const TOKEN_PREFIXES = ["ExponentPushToken[", "ExpoPushToken["];
const TOKEN_MAX_LENGTH = 255;

/**
 * 서버가 받아 주는 Expo 푸시 토큰 모양인지(서버 검증과 같은 규칙).
 * @param {unknown} token
 * @returns {boolean}
 */
export function isUsableToken(token) {
  return (
    typeof token === "string" &&
    token.length <= TOKEN_MAX_LENGTH &&
    token.endsWith("]") &&
    TOKEN_PREFIXES.some((prefix) => token.startsWith(prefix))
  );
}

/**
 * 푸시를 눌렀을 때 이동할 화면 경로. 1단계는 항상 알림함이다(분류별 이동은 후속).
 * @param {{ kind?: string, notification_id?: string } | null | undefined} data 푸시에 담긴 data
 * @returns {string}
 */
export function routeForPush(data) {
  void data;
  return "/notifications";
}

/**
 * 푸시 토큰을 받아 서버에 등록해도 되는 상태인지: 로그인했고 웹이 아닐 때만.
 * @param {{ status: string, platform: string }} state
 * @returns {boolean}
 */
export function shouldRegister({ status, platform }) {
  return status === "authenticated" && platform !== "web";
}

/**
 * 끈 알림 분류 목록에서 한 분류를 켜거나 끈다(있으면 빼고 없으면 더한다). 입력은 바꾸지 않는다.
 * @param {string[] | undefined} muted 끈 분류 목록
 * @param {string} kind 알림 분류
 * @returns {string[]}
 */
export function toggleKind(muted, kind) {
  const list = muted ?? [];
  return list.includes(kind) ? list.filter((k) => k !== kind) : [...list, kind];
}
