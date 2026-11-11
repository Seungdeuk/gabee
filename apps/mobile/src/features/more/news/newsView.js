// 마이 > AI 리포트 > 가족 뉴스 카드: 서버 응답을 화면 상태로 바꾸는 순수 함수(화면·네트워크 없음).

/** 새로 만들 수 있는 가장 오래된 주(offset). 서버가 이번 주·지난 주만 만든다. */
const OLDEST_CREATABLE_OFFSET = -1;

const SAVED_NOTE = "일정을 지워도 이미 만든 뉴스는 그대로 남아요.";

/**
 * 그 주(offset)의 뉴스를 새로 만들 수 있는지.
 * @param {number} offset 0=이번 주, -1=지난 주, …
 * @returns {boolean}
 */
export function canCreateNews(offset) {
  return offset >= OLDEST_CREATABLE_OFFSET && offset <= 0;
}

/**
 * 오류를 카드 안 알림 문구로 바꾼다. retry 가 true 면 같은 요청을 다시 해 볼 만하다.
 * @param {unknown} error
 * @returns {{ title: string, message: string, retry: boolean }}
 */
export function describeNewsError(error) {
  const code = error && typeof error === "object" && "code" in error ? error.code : "";
  switch (code) {
    case "ai_not_enabled":
      return {
        title: "가족 AI가 꺼져 있어요",
        message: "가족 AI 기능을 켜면 뉴스를 만들 수 있어요. 가족 소유자나 관리자가 켤 수 있어요.",
        retry: false,
      };
    case "ai_daily_limit_user":
      return { title: "오늘은 다 썼어요", message: "오늘 쓸 수 있는 AI 요청 횟수를 모두 썼어요. 내일 다시 만들 수 있어요.", retry: false };
    case "ai_daily_limit_group":
      return { title: "오늘은 다 썼어요", message: "우리 가족이 오늘 쓸 수 있는 AI 요청 횟수를 모두 썼어요. 내일 다시 만들 수 있어요.", retry: false };
    case "ai_cooldown": {
      const wait = Number(error.retryAfter) > 0 ? `${Math.floor(Number(error.retryAfter))}초 뒤에` : "조금 뒤에";
      return { title: "잠시 후에 다시 해 주세요", message: `AI 요청은 간격을 두고 보낼 수 있어요. ${wait} 다시 눌러 주세요.`, retry: true };
    }
    case "news_not_ready":
      return { title: "아직 만들 수 없어요", message: "이번 주 뉴스는 일요일 저녁부터 만들 수 있어요.", retry: false };
    case "news_week_too_old":
      return { title: "만들 수 없는 주예요", message: "뉴스는 이번 주와 지난 주만 새로 만들 수 있어요.", retry: false };
    case "llm_unavailable":
      return { title: "지금은 만들 수 없어요", message: "AI 기능이 아직 서버에 설정되지 않았어요. 가족 관리자에게 알려 주세요.", retry: false };
    case "invalid_week":
      return { title: "만들 수 없는 주예요", message: "이 주의 뉴스는 만들 수 없어요.", retry: false };
    case "ai_busy":
    case "llm_failed":
      return { title: "뉴스를 만들지 못했어요", message: "AI 요청을 처리하지 못했어요. 잠시 뒤에 다시 시도해 주세요.", retry: true };
    default:
      return { title: "불러오지 못했어요", message: "잠시 뒤에 다시 시도해 주세요.", retry: true };
  }
}

/**
 * 문장 하나의 근거 목록(없는 id 는 건너뛴다).
 * @param {{ source_ids?: string[] }} item
 * @param {{ id: string, kind: string, label: string }[]} sources
 * @returns {{ id: string, kind: string, ref: string, label: string, date?: string | null }[]}
 */
export function sentenceSources(item, sources) {
  const byId = new Map((sources ?? []).map((s) => [s.id, s]));
  return (item?.source_ids ?? []).map((id) => byId.get(id)).filter(Boolean);
}

/**
 * 문장을 눌렀을 때 갈 곳. 일정·할 일 근거가 하나라도 있으면 일정 탭, 문서뿐이면 이동하지 않는다.
 * @param {{ source_ids?: string[] }} item
 * @param {{ id: string, kind: string }[]} sources
 * @returns {"/schedule" | null}
 */
export function itemRoute(item, sources) {
  return sentenceSources(item, sources).some((s) => s.kind === "event" || s.kind === "todo") ? "/schedule" : null;
}

/**
 * 가족 뉴스 카드가 그릴 내용.
 * kind: loading | error | ready | offer | pending | too_early | empty | failed | missing
 * action: 카드의 버튼이 하는 일(create=뉴스 만들기, reload=다시 불러오기). 없으면 버튼이 없다.
 * @param {{
 *   phase: "loading" | "loaded" | "error",
 *   offset: number,
 *   news?: { status: string, title?: string | null, items?: object[], sources?: object[] } | null,
 *   creating?: boolean,
 *   createError?: unknown,
 *   error?: unknown,
 * }} input
 * @returns {{ kind: string, title?: string, message?: string, items?: object[], sources?: object[], note?: string, action?: "create" | "reload", actionLabel?: string, busy?: boolean, notice?: { title: string, message: string } }}
 */
export function newsCardView({ phase, offset, news, creating = false, createError, error }) {
  if (phase === "loading") return { kind: "loading" };
  if (phase === "error" || !news) {
    const e = describeNewsError(error);
    return { kind: "error", title: e.title, message: e.message, action: "reload", actionLabel: "다시 불러오기" };
  }
  const failure = createError ? describeNewsError(createError) : null;
  const notice = failure ? { title: failure.title, message: failure.message } : undefined;
  const stuck = Boolean(failure) && !failure.retry; // 다시 눌러도 같은 오류가 나는 경우: 버튼을 잠근다
  const create = canCreateNews(offset);
  switch (news.status) {
    case "ready":
      return { kind: "ready", title: news.title || "가족 뉴스", items: news.items ?? [], sources: news.sources ?? [], note: SAVED_NOTE };
    case "pending":
      return { kind: "pending", message: "뉴스를 만들고 있어요. 다 되면 이 자리에 보여 드릴게요." };
    case "too_early":
      return { kind: "too_early", message: "이번 주 뉴스는 일요일 저녁 이후에 만들 수 있어요." };
    case "empty":
      return {
        kind: "empty",
        message: "공유한 일정·할 일·문서가 없어서 뉴스를 만들지 못했어요. 공유한 뒤에 다시 확인할 수 있어요.",
        notice,
        ...(create ? { action: "create", actionLabel: "다시 확인하기", busy: creating || stuck } : {}),
      };
    case "failed":
      return {
        kind: "failed",
        message: "뉴스를 만들지 못했어요. 아래 리포트는 그대로 볼 수 있어요.",
        notice,
        ...(create ? { action: "create", actionLabel: "다시 시도", busy: creating || stuck } : {}),
      };
    default:
      if (!create) return { kind: "missing", message: "이 주의 뉴스는 만들어지지 않았어요. 뉴스는 이번 주와 지난 주만 만들 수 있어요." };
      return {
        kind: "offer",
        message: offset === 0 ? "이번 주 공유 기록으로 가족 뉴스를 만들어 드려요." : "지난 주 공유 기록으로 가족 뉴스를 만들어 드려요.",
        notice,
        action: "create",
        actionLabel: creating ? "만드는 중…" : "뉴스 만들기",
        busy: creating || stuck,
      };
  }
}
