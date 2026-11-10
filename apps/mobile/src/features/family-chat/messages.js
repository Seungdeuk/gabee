import { usedRatio } from "../../shared/aiUsage.js";

/**
 * 가족 채팅(AI) 오류(ApiError)와 결과를 사용자에게 보여줄 한국어 문장으로 바꾼다. 대화 내용은 문장에 넣지 않는다.
 */
const BY_CODE = {
  network_error: "서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요",
  api_not_configured: "서버 주소가 설정되지 않아 이 기능을 쓸 수 없어요",
  ai_not_enabled: "AI 기능이 아직 켜지지 않았어요. 잠시 뒤 다시 눌러 주세요",
  not_manager: "가족 소유자나 관리자만 바꿀 수 있어요",
  too_few_messages: "분석할 대화가 아직 충분하지 않아요. 대화가 조금 더 쌓인 뒤에 눌러 주세요",
  ai_daily_limit_user: "오늘 내가 쓸 수 있는 AI 횟수를 모두 썼어요. 내일 다시 이용해 주세요",
  ai_daily_limit_group: "오늘 우리 가족이 쓸 수 있는 AI 횟수를 모두 썼어요. 내일 다시 이용해 주세요",
  ai_busy: "다른 AI 요청이 처리되고 있어요. 끝난 뒤에 다시 눌러 주세요",
  llm_unavailable: "AI 기능이 아직 서버에 설정되지 않았어요. 서버 관리자에게 AI 설정을 부탁해 주세요",
  llm_failed: "AI가 결과를 만들지 못했어요. 잠시 후 다시 시도해 주세요",
  no_group: "가족 그룹에 먼저 참여해 주세요",
  peer_left: "상대가 이 대화방을 나가서 AI를 쓸 수 없어요", // 방만 나갔든 가족을 나갔든 같은 코드라 원인을 가리지 않는다
  peer_left_room: "상대방이 나가서 메시지를 보낼 수 없어요",
  cannot_leave_family_room: "가족 전체방은 나갈 수 없어요",
  token_required: "로그인이 필요해요",
  token_invalid: "로그인이 필요해요",
  session_expired: "로그인이 만료됐어요. 다시 로그인해 주세요",
};

/** 초를 "30초" / "2분" 으로. @param {number} seconds */
function waitText(seconds) {
  return seconds < 60 ? `${seconds}초` : `${Math.ceil(seconds / 60)}분`;
}

/**
 * @param {{ code?: string, message?: string, retryAfter?: number } | null | undefined} error
 * @returns {string}
 */
export function chatErrorMessage(error) {
  if (!error) return "";
  if (error.code === "ai_cooldown" || error.code === "too_many_requests") {
    const wait = error.retryAfter ? ` (${waitText(error.retryAfter)} 뒤에 다시 시도할 수 있어요)` : "";
    return `AI를 너무 자주 요청했어요. 잠시 후 다시 눌러 주세요${wait}`;
  }
  return BY_CODE[error.code] ?? error.message ?? "요청을 처리하지 못했어요";
}

/**
 * AI 결과의 한 줄 설명. 캐시면 AI 를 부르지 않은 저장된 결과다. 호출 수·토큰은 작게 덧붙인다.
 * @param {{ cached?: boolean, api_calls?: number, input_tokens?: number, output_tokens?: number } | null | undefined} meta
 * @returns {string}
 */
export function resultCaption(meta) {
  if (!meta) return "";
  if (meta.cached) return "저장된 결과(AI 호출 없음)";
  const tokens = (meta.input_tokens ?? 0) + (meta.output_tokens ?? 0);
  return `방금 분석 · AI 호출 ${meta.api_calls ?? 1}번 · 토큰 ${tokens}`;
}

/**
 * 분석에 쓴 범위 설명. 예: "대화 24개 기준 · 오후 3:20"
 * @param {{ message_count?: number, generated_at?: string } | null | undefined} meta
 * @returns {string}
 */
export function rangeCaption(meta) {
  if (!meta) return "";
  const at = new Date(meta.generated_at);
  const time = Number.isNaN(at.getTime())
    ? ""
    : ` · ${at.getHours() < 12 ? "오전" : "오후"} ${at.getHours() % 12 || 12}:${String(at.getMinutes()).padStart(2, "0")}`;
  return `대화 ${meta.message_count ?? 0}개 기준${time}`;
}

/**
 * 일정 후보를 일정으로 등록할 수 있는지(날짜·시간이 둘 다 있어야 한다). 없는 값은 지어내지 않는다.
 * @param {{ date?: string | null, time?: string | null } | null | undefined} candidate
 * @returns {boolean}
 */
export function canRegisterSchedule(candidate) {
  return Boolean(candidate?.date) && Boolean(candidate?.time);
}

/**
 * 일정 후보에서 정해지지 않은 부분 안내. 모두 정해졌으면 빈 문자열.
 * @param {{ date?: string | null, time?: string | null } | null | undefined} candidate
 * @returns {string}
 */
export function scheduleMissingNote(candidate) {
  return canRegisterSchedule(candidate) ? "" : "날짜·시간이 정해지지 않았어요";
}

/**
 * 설정 응답을 화면에서 쓰는 형태로 정리한다(빠진 값은 안전한 쪽으로).
 * @param {object | null | undefined} raw
 * @returns {{ enabled: boolean, canManage: boolean, userLeft: number | null, groupLeft: number | null, userUsedRatio: number | null, groupUsedRatio: number | null, cooldownSeconds: number }}
 *   Left 는 남은 횟수, UsedRatio 는 한도 대비 사용한 비율(0~1)이다. 화면은 횟수 대신 "N% 사용됨" 게이지를 보인다.
 */
export function parseAiSettings(raw) {
  const left = (limit, used) => (Number.isFinite(limit) && Number.isFinite(used) ? Math.max(0, limit - used) : null);
  return {
    enabled: raw?.enabled === true,
    canManage: raw?.can_manage === true,
    userLeft: left(raw?.limits?.user_per_day, raw?.usage?.user_today),
    groupLeft: left(raw?.limits?.group_per_day, raw?.usage?.group_today),
    userUsedRatio: usedRatio(raw?.limits?.user_per_day, raw?.usage?.user_today),
    groupUsedRatio: usedRatio(raw?.limits?.group_per_day, raw?.usage?.group_today),
    cooldownSeconds: Number(raw?.limits?.cooldown_seconds) || 0,
  };
}

/**
 * 대화 분석 응답을 화면용으로 다듬는다. 구 서버 응답에 replies·topics 가 없거나 배열이 아니면 빈 배열로 둔다.
 * @param {object | null | undefined} res analyzeChat 응답
 * @returns {{ summary: string, important_messages: object[], schedule_candidates: object[], todo_candidates: object[], replies: string[], topics: string[], meta: object | undefined }}
 */
export function parseAnalysis(res) {
  const list = (v) => (Array.isArray(v) ? v : []);
  const texts = (v) => list(v).filter((t) => typeof t === "string" && t.trim() !== "");
  return {
    summary: res?.summary ?? "",
    important_messages: list(res?.important_messages),
    schedule_candidates: list(res?.schedule_candidates),
    todo_candidates: list(res?.todo_candidates),
    replies: texts(res?.replies),
    topics: texts(res?.topics),
    meta: res?.meta,
  };
}

/**
 * AI 패널이 설정을 불러와야 하는지. 패널이 닫혀 있으면 어떤 호출도 하지 않는다(분석·추천은 버튼에서만).
 * @param {boolean} visible 패널이 열려 있는지
 * @returns {boolean}
 */
export function shouldLoadSettings(visible) {
  return visible === true;
}
