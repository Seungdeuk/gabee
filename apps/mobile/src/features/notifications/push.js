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

/** 소통 메시지 푸시에 무엇을 보일지 고르는 선택지(서버 `preview_mode` 값과 같다). */
export const PREVIEW_OPTIONS = [
  { key: "full", label: "내용 보이기" },
  { key: "sender", label: "보낸 사람만" },
  { key: "hidden", label: "숨기기" },
];

const QUIET_PRESET = { quiet_start: "22:00", quiet_end: "07:00" };

/**
 * 방해금지(밤 10시~아침 7시)가 켜져 있는지. 서버는 "22:00:00" 처럼 초까지 돌려준다.
 * @param {{ quiet_start?: string | null, quiet_end?: string | null }} settings
 * @returns {boolean}
 */
export function isQuietOn(settings) {
  return Boolean(settings?.quiet_start && settings?.quiet_end);
}

/**
 * 방해금지를 켜거나 끈 새 설정을 만든다(입력은 바꾸지 않는다). 시간은 밤 10시~아침 7시로 정해 둔다.
 * @template {{ quiet_start?: string | null, quiet_end?: string | null }} T
 * @param {T} settings
 * @param {boolean} on
 * @returns {T}
 */
export function withQuiet(settings, on) {
  return { ...settings, ...(on ? QUIET_PRESET : { quiet_start: null, quiet_end: null }) };
}
