// 마이 > 우리 가족 뉴스: 서버 응답을 화면 상태로 바꾸는 순수 함수(화면·네트워크 없음).

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

/** 가비 기자 인사(고정 문구, AI 호출 없음). */
export const REPORTER_GREETING = "가비 기자가 전하는 우리 가족 한 주 이야기";

const KIND_CATEGORY = { event: "일정", todo: "할 일", document: "문서" };
const MIXED_CATEGORY = "가족 소식";

/**
 * 기사 분류 이름. 서버가 준 category 를 쓰고, 옛 뉴스(v1)처럼 없으면 근거 종류로 정한다(하나면 그 종류, 섞이면 "가족 소식", 근거가 없으면 null).
 * @param {{ category?: string | null, source_ids?: string[] }} item
 * @param {{ id: string, kind: string }[] | undefined} sources
 * @returns {string | null}
 */
export function categoryOf(item, sources) {
  if (item?.category) return item.category;
  const kinds = new Set(sentenceSources(item, sources).map((s) => s.kind));
  if (kinds.size === 0) return null;
  if (kinds.size > 1) return MIXED_CATEGORY;
  return KIND_CATEGORY[[...kinds][0]] ?? null;
}

/**
 * 뉴스 항목을 메인 기사 하나와 단신으로 나눈다. role 이 lead 인 첫 항목이 메인이고(옛 뉴스처럼 role 이 없으면 첫 항목),
 * 나머지는 받은 순서(서버가 이른 날짜 순으로 준다) 그대로 단신이다. 헤드라인이 없으면 본문을 제목처럼 보이고 본문은 비운다.
 * @param {{ text: string, headline?: string | null, role?: string | null, category?: string | null, source_ids?: string[] }[] | undefined} items
 * @param {{ id: string, kind: string }[] | undefined} sources
 * @returns {{ lead: object | null, briefs: object[] }} 기사: { headline, body, category, item }
 */
export function splitArticles(items, sources) {
  const list = Array.isArray(items) ? items : [];
  if (list.length === 0) return { lead: null, briefs: [] };
  const article = (item) => ({
    headline: item.headline || item.text,
    text: item.text,
    // 보일 본문: 헤드라인이 없거나 제목과 같은 말뿐이면 비운다(제목 + 날짜 + 근거만 보인다)
    body: item.headline && !isRedundantBody(item.headline, item.text) ? item.text : "",
    category: categoryOf(item, sources),
    date: articleDate(item, sources),
    item,
  });
  const leadIndex = Math.max(0, list.findIndex((i) => i.role === "lead"));
  return {
    lead: article(list[leadIndex]),
    briefs: list.filter((_, i) => i !== leadIndex).map(article),
  };
}

/**
 * 주차 표시. 서버가 준 issue_year·issue_no(서버 주 계산의 ISO 주차)를 그대로 쓴다. 실제 발행 번호가 아니라 연중 주차라서
 * "제 N호"가 아니라 "N주차"로 보인다. 없거나 올바르지 않으면 null.
 * @param {{ issue_no?: number, issue_year?: number } | null | undefined} news
 * @returns {string | null}
 */
export function issueLabel(news) {
  const no = news?.issue_no;
  const year = news?.issue_year;
  if (!Number.isInteger(no) || no < 1 || !Number.isInteger(year)) return null;
  return `${year}년 ${no}주차`;
}

/** 선택한 주와 상관없이 쓰는 문구(이번 주·지난 주 표현을 쓰지 않는다). */
export const LEAD_KICKER = "이 주의 주요 소식";
export const SECTION_LABEL = "이 주의 소식";

/**
 * 소식(기사) 수에 따른 화면 구성: 1개는 짧은 기사 카드 하나, 2~3개는 메인 기사 + 단신, 4개 이상은 메인 기사 + 기사 목록, 0개는 없음.
 * @param {number | undefined} count
 * @returns {"none" | "single" | "lead_brief" | "lead_list"}
 */
export function articleLayout(count) {
  if (!Number.isInteger(count) || count < 1) return "none";
  if (count === 1) return "single";
  return count <= 3 ? "lead_brief" : "lead_list";
}

const SPLIT = /[\s.,!?·~…"'“”‘’()[\]{}\-–—:;/]+/;

/**
 * 글을 낱말(공백·문장부호 기준)로 나눈다. 빈 조각은 버린다.
 * @param {string | null | undefined} text
 * @returns {string[]}
 */
const wordsOf = (text) => String(text ?? "").split(SPLIT).filter(Boolean);

// 일정을 일정으로 알리는 상투 표현(서버가 약속 본문에 요구하는 표현과 완료·등록 표현). 제목과 같은 말을 다시 하는 데만 쓰이므로 새 정보가 아니다.
const BOILERPLATE = ["있었", "잡혀", "예정", "등록", "공유", "마쳤", "완료", "올라왔", "올렸", "일정", "약속"];

/**
 * 본문이 제목과 같은 정보만 되풀이하는지. 본문이 비었거나, 본문의 **모든 낱말**이 제목의 낱말(조사가 붙은 꼴 포함)이거나 일정 상투 표현이면
 * 중복이다(제목 + 날짜 + 근거만 보이게 본문을 숨긴다). 제목에 없는 낱말(숫자·시각·취소·연기·수량 등)이 하나라도 있으면 새 정보라 숨기지 않는다.
 * 제목이 없으면 비교할 수 없어 중복이 아니다.
 * @param {string | null | undefined} headline
 * @param {string | null | undefined} body
 * @returns {boolean}
 */
export function isRedundantBody(headline, body) {
  const text = String(body ?? "").trim();
  if (!text) return true;
  const head = wordsOf(headline).filter((w) => w.length >= 2);
  if (head.length === 0) return false;
  const covered = (w) => head.some((h) => w.includes(h) || h.includes(w)) || BOILERPLATE.some((b) => w.includes(b));
  return wordsOf(text).every(covered);
}

const WEEKDAY_LETTERS = "일월화수목금토";

/**
 * "YYYY-MM-DD" 를 달력 날짜(기기 시간대와 무관한 UTC 기준)로 읽는다. 형식이 틀리거나 없는 날짜(2월 30일 등)면 null.
 * @param {unknown} value
 * @returns {{ y: number, mo: number, d: number, time: number, wd: string } | null}
 */
function parseYmd(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? ""));
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const date = new Date(Date.UTC(y, mo - 1, d));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== d) return null;
  return { y, mo, d, time: date.getTime(), wd: WEEKDAY_LETTERS[date.getUTCDay()] };
}

/**
 * 기사 날짜 표시: 근거 일정들의 날짜. 하루면 "11월 3일(화)", 여러 날이면 "11월 3일(화) ~ 5일(목)", 날짜가 없으면 null.
 * @param {{ source_ids?: string[] }} item
 * @param {{ id: string, date?: string | null }[] | undefined} sources
 * @returns {string | null}
 */
export function articleDate(item, sources) {
  const dates = sentenceSources(item, sources)
    .map((s) => parseYmd(s.date))
    .filter(Boolean)
    .sort((a, b) => a.time - b.time);
  if (dates.length === 0) return null;
  const first = dates[0];
  const last = dates[dates.length - 1];
  const show = (x, withMonth) => `${withMonth ? `${x.mo}월 ` : ""}${x.d}일(${x.wd})`;
  if (first.time === last.time) return show(first, true);
  const sameMonth = first.y === last.y && first.mo === last.mo;
  return `${show(first, true)} ~ ${show(last, !sameMonth)}`;
}

/**
 * 지금 보는 주(weekStart)의 응답일 때만 호수를 보인다. 주를 바꾸는 동안(이전 주 응답이 남아 있다)이나 조회가 실패했을 때
 * 이전 주의 호수가 새 날짜 옆에 남지 않게 한다.
 * @param {{ week_start?: string, issue_no?: number, issue_year?: number } | null | undefined} news
 * @param {string} weekStart 지금 보는 주의 월요일(YYYY-MM-DD)
 * @returns {string | null}
 */
export function issueForWeek(news, weekStart) {
  return news?.week_start === weekStart ? issueLabel(news) : null;
}

/**
 * "한 주의 기록" 접힌 영역의 요약 한 줄. 문서를 불러오지 못했으면 조용히 빼지 않고 그렇다고 알린다.
 * @param {{ sharedCount: number, todoDone: number, docCount: number | null } | null | undefined} report
 * @param {"ok" | "loading" | "failed"} [docsStatus]
 * @returns {string}
 */
export function recordSummary(report, docsStatus) {
  if (!report) return "";
  const parts = [`공유 일정 ${report.sharedCount}건`, `완료한 할 일 ${report.todoDone}건`];
  if (report.docCount !== null && report.docCount !== undefined) parts.push(`공유 문서 ${report.docCount}건`);
  else if (docsStatus === "failed") parts.push("문서를 불러오지 못했어요");
  return parts.join(" · ");
}

/**
 * "한 주의 기록"을 처음에 펼칠지. 뉴스가 읽힌 주는 접고, 뉴스가 없거나 불러오지 못한 주는 펼친다. 문서를 불러오지 못했으면
 * 알림이 보이도록 펼친다. 뉴스를 받는 중이거나 아직 다른 주의 응답이면 정하지 않고 접어 둔다(펼쳤다 접히며 화면이 튀지 않게).
 * @param {{ phase: "loading" | "loaded" | "error", news: { status?: string, week_start?: string } | null | undefined, weekStart: string, docsStatus?: "ok" | "loading" | "failed" }} input
 * @returns {boolean}
 */
export function recordDefaultOpen({ phase, news, weekStart, docsStatus }) {
  if (docsStatus === "failed") return true;
  if (phase === "error") return true;
  if (phase !== "loaded" || news?.week_start !== weekStart) return false;
  return news.status !== "ready" || !(Array.isArray(news.items) && news.items.length > 0);
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
      return {
        kind: "ready",
        title: news.title || "가족 뉴스",
        items: news.items ?? [],
        sources: news.sources ?? [],
        note: SAVED_NOTE,
        ...splitArticles(news.items, news.sources),
        issue: issueLabel(news),
        layout: articleLayout(Array.isArray(news.items) ? news.items.length : 0),
      };
    case "pending":
      return { kind: "pending", message: "뉴스를 만들고 있어요. 다 되면 이 자리에 보여 드릴게요." };
    case "too_early":
      return { kind: "too_early", message: "이번 주 뉴스는 일요일 저녁 이후에 만들 수 있어요." };
    case "empty":
      return {
        kind: "empty",
        message: "이 주에는 발행할 소식이 없어요. 공유한 일정·할 일·문서가 생기면 다시 확인할 수 있어요.",
        notice,
        ...(create ? { action: "create", actionLabel: "다시 확인하기", busy: creating || stuck } : {}),
      };
    case "failed":
      return {
        kind: "failed",
        message: "뉴스를 만들지 못했어요. 아래 한 주의 기록은 그대로 볼 수 있어요.",
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
