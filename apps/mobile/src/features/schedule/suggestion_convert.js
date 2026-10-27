// 서버 추천(/schedule/suggestions, 채팅 suggestion 카드)을 화면이 쓰는 제안 모양으로 바꾸는 순수 함수들. 화면·테마에 의존하지 않아 node 테스트로 확인한다.

const KIND_FROM_SERVER = { 1: "appointment", 2: "todo" };

/**
 * 서버 제안 한 건 → 화면 제안. 날짜는 절대 날짜(draft.date)다. 채팅 카드는 date, 목록은 start_date 로 온다.
 * @param {{ id: string, title: string, kind: 1 | 2, start_date?: string, date?: string, place?: string }} s
 * @returns {{ id: string, name: string, draft: { kind: "appointment" | "todo", title: string, date: string, place: string } }}
 */
export function fromServerSuggestion(s) {
  return {
    id: s.id,
    name: s.title,
    draft: { kind: KIND_FROM_SERVER[s.kind] ?? "appointment", title: s.title, date: s.start_date ?? s.date ?? "", place: s.place ?? "" },
  };
}

/** "YYYY-MM-DD" 에 일수를 더한다(기기 날짜 기준, 시각 변환 없이 달력 계산). */
function plusDays(day, n) {
  const [y, m, d] = day.split("-").map(Number);
  const t = new Date(y, m - 1, d + n);
  const pad = (v) => String(v).padStart(2, "0");
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
}

/**
 * 제안이 가리키는 날짜. 서버 제안은 draft.date(절대), 예전 mock 은 draft.daysFromToday(오늘 기준).
 * @param {{ date?: string, daysFromToday?: number }} draft
 * @param {string} today "YYYY-MM-DD"
 */
export function draftDateOf(draft, today) {
  return draft.date ? draft.date : plusDays(today, draft.daysFromToday ?? 0);
}

/**
 * 등록 화면에 넘길 서버 제안 정보(제안 id·장소). 예전 임시 제안에는 id 가 없어 아무것도 넘기지 않는다.
 * @param {{ id?: string, draft: { place?: string } }} suggestion
 * @returns {{ suggestionId?: string, place?: string }}
 */
export function suggestionExtras(suggestion) {
  const extras = {};
  if (suggestion.draft.place) extras.place = suggestion.draft.place;
  if (suggestion.id && suggestion.draft.date) extras.suggestionId = suggestion.id;
  return extras;
}
