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
 * 푸시를 눌렀을 때 이동할 화면 경로. 알림함 사건은 알림함으로, 소통 푸시(kind=chat)는 그 채팅방으로 간다.
 * 푸시에는 방 id 만 있어서 방 종류·상대는 채팅방을 여는 길(`/chat-open`)이 방 목록으로 찾는다(방 id 가 없으면 소통 탭 목록).
 * @param {{ kind?: string, notification_id?: string, room_id?: unknown } | null | undefined} data 푸시에 담긴 data
 * @returns {string}
 */
export function routeForPush(data) {
  if (data?.kind === "chat") {
    return typeof data.room_id === "string" && data.room_id ? `/chat-open?roomId=${encodeURIComponent(data.room_id)}` : "/family-chat";
  }
  if (data?.kind === "schedule" && (data.event === "event_soon" || data.event === "todo_due")) return "/schedule"; // 예약 푸시(일정 30분 전·할 일 아침)는 일정 탭으로
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

/**
 * 기기 알림 권한 상태를 화면에서 쓰는 네 가지로 나눈다.
 * @param {{ status?: string, canAskAgain?: boolean } | null | undefined} permission expo-notifications getPermissionsAsync 결과
 * @returns {"granted" | "ask" | "blocked" | "unknown"} granted 허용됨 · ask 아직 묻지 않았거나 다시 물을 수 있음 · blocked 기기 설정에서만 켤 수 있음 · unknown 알 수 없음(웹 등)
 */
export function permissionState(permission) {
  if (!permission || typeof permission.status !== "string") return "unknown";
  if (permission.status === "granted") return "granted";
  return permission.canAskAgain === false ? "blocked" : "ask";
}

/**
 * 푸시를 켜 둔 사람에게 보일 기기 권한 안내. 문제가 없거나 푸시를 꺼 둔 사람에게는 null 이다.
 * @param {"granted" | "ask" | "blocked" | "unknown" | "failed"} state permissionState 결과(또는 등록 실패 "failed")
 * @param {boolean} enabled 서버 푸시 설정이 켜져 있는지
 * @returns {{ text: string, action: "allow" | "settings" | null, actionLabel?: string } | null}
 */
export function permissionNotice(state, enabled) {
  if (!enabled) return null;
  if (state === "ask") return { text: "이 기기에서 알림을 아직 허용하지 않았어요. 허용해야 푸시가 와요.", action: "allow", actionLabel: "알림 허용하기" };
  if (state === "blocked") return { text: "기기의 알림 권한이 꺼져 있어요. 기기 설정에서 켜면 푸시를 받을 수 있어요.", action: "settings", actionLabel: "기기 설정 열기" };
  if (state === "failed") return { text: "이 기기에서는 푸시를 받을 준비를 하지 못했어요. 알림함에서는 그대로 볼 수 있어요.", action: null };
  return null;
}

const QUIET_PRESET = { quiet_start: "22:00", quiet_end: "07:00" };

/**
 * 방해금지가 켜져 있는지(시작·끝이 둘 다 있을 때). 서버는 "22:00:00" 처럼 초까지 돌려준다.
 * @param {{ quiet_start?: string | null, quiet_end?: string | null }} settings
 * @returns {boolean}
 */
export function isQuietOn(settings) {
  return Boolean(settings?.quiet_start && settings?.quiet_end);
}

/**
 * "22:00" 또는 "22:00:00" 을 시·분으로 읽는다.
 * @param {unknown} value
 * @returns {{ hour: number, minute: number } | null} 읽을 수 없으면 null
 */
export function parseTime(value) {
  const match = typeof value === "string" ? /^(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/.exec(value) : null;
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour <= 23 && minute <= 59 ? { hour, minute } : null;
}

/**
 * 시·분을 서버로 보내는 "HH:MM" 으로 만든다.
 * @param {{ hour: number, minute: number }} time
 * @returns {string}
 */
export function toClockString({ hour, minute }) {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

/**
 * 시각을 "오후 10:00" 처럼 읽기 쉬운 한국어로 쓴다.
 * @param {string | null | undefined} value "HH:MM" 또는 "HH:MM:SS"
 * @returns {string} 읽을 수 없으면 빈 문자열
 */
export function formatTimeKorean(value) {
  const time = parseTime(value);
  if (!time) return "";
  const hour12 = time.hour % 12 === 0 ? 12 : time.hour % 12;
  return `${time.hour < 12 ? "오전" : "오후"} ${hour12}:${String(time.minute).padStart(2, "0")}`;
}

/**
 * 방해금지를 켜거나 끈 새 설정을 만든다(입력은 바꾸지 않는다). 처음 켜면 밤 10시~아침 7시, 이미 켜져 있으면 정해 둔 시간을 "HH:MM" 으로 유지한다.
 * @template {{ quiet_start?: string | null, quiet_end?: string | null }} T
 * @param {T} settings
 * @param {boolean} on
 * @returns {T}
 */
export function withQuiet(settings, on) {
  if (!on) return { ...settings, quiet_start: null, quiet_end: null };
  const start = parseTime(settings?.quiet_start);
  const end = parseTime(settings?.quiet_end);
  if (start && end && toClockString(start) !== toClockString(end)) {
    return { ...settings, quiet_start: toClockString(start), quiet_end: toClockString(end) };
  }
  return { ...settings, ...QUIET_PRESET };
}

/**
 * 시작 또는 끝 시각의 시(1시간씩, 0~23 순환)나 분(5분씩, 0~55 순환)을 줄이거나 늘린 새 설정을 만든다(입력은 바꾸지 않는다).
 * 시작과 끝이 같아지면 서버에서 방해금지가 걸리지 않으므로 한 칸 더 건너뛴다. 방해금지가 꺼져 있으면 그대로 돌려준다.
 * @template {{ quiet_start?: string | null, quiet_end?: string | null }} T
 * @param {T} settings
 * @param {"quiet_start" | "quiet_end"} field 바꿀 쪽
 * @param {"hour" | "minute"} unit
 * @param {1 | -1} direction 1 이면 늘리고 -1 이면 줄인다
 * @returns {T}
 */
export function stepQuietTime(settings, field, unit, direction) {
  const current = parseTime(settings?.[field]);
  const other = parseTime(settings?.[field === "quiet_start" ? "quiet_end" : "quiet_start"]);
  if (!current || !other) return settings;
  const step = (time) =>
    unit === "hour"
      ? { hour: (time.hour + direction + 24) % 24, minute: time.minute }
      : { hour: time.hour, minute: ((Math.round(time.minute / 5) + direction) * 5 + 60) % 60 };
  let next = step(current);
  if (toClockString(next) === toClockString(other)) next = step(next);
  if (toClockString(next) === toClockString(other)) return settings;
  return { ...settings, [field]: toClockString(next) };
}

/**
 * 방해금지 안내 문구. 끝이 시작보다 이르거나 같으면 다음 날 끝나는 것이다.
 * @param {{ quiet_start?: string | null, quiet_end?: string | null }} settings
 * @returns {string} 시간을 읽을 수 없으면 빈 문자열
 */
export function formatQuietSummary(settings) {
  const start = parseTime(settings?.quiet_start);
  const end = parseTime(settings?.quiet_end);
  if (!start || !end) return "";
  const nextDay = toClockString(end) <= toClockString(start);
  return `${toClockString(start)} ~ ${nextDay ? "다음 날 " : ""}${toClockString(end)}에는 푸시를 보내지 않아요`;
}

/**
 * 이 기기에서 서버에 올린(또는 올리려던) 푸시 토큰을 기억하고, 등록하는 도중에 로그아웃(해제)이 지나갔는지 알려 준다.
 * 토큰은 서버에 보내기 전에 기억해 두므로, 등록 요청이 실패해도 로그아웃 때 해제를 시도할 수 있다.
 * @returns {{ begin: () => number, remember: (token: string) => void, current: () => string | null, isStale: (startedAt: number) => boolean, take: () => string | null }}
 */
export function createTokenTracker() {
  let token = null;
  let epoch = 0;
  return {
    /** 등록을 시작할 때 부른다. 돌려준 번호를 isStale 에 넘긴다. */
    begin: () => epoch,
    remember(next) {
      token = next;
    },
    current: () => token,
    /** begin() 이후 해제(take)가 있었으면 true. */
    isStale: (startedAt) => startedAt !== epoch,
    /** 해제하려고 기억한 토큰을 꺼낸다(없으면 null). 이후 시작한 등록과 구분되도록 번호가 올라간다. */
    take() {
      epoch += 1;
      const taken = token;
      token = null;
      return taken;
    },
  };
}
