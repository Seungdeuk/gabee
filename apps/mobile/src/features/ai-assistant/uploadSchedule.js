// 문서·사진을 올려 분석이 끝난 직후 "이런 내용이네요, 일정에 넣을까요?" 를 물을지 정하는 규칙(순수 함수, 시험: tests/uploadschedule.test.js)
// AI 를 따로 부르지 않는다: 분석 결과의 날짜(occurred_on)가 오늘 이후일 때만 묻고, 사용자가 "일정에 넣기"를 누르면 그때 채팅으로 요청한다.

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** 기기의 오늘 날짜(YYYY-MM-DD). */
export function localToday(now = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * 올린 기록에서 일정으로 넣을 만한 날짜가 있으면 카드에 쓸 값을 돌려준다.
 * 지난 날짜(영수증·결제 내역)나 날짜가 없는 기록은 묻지 않는다.
 * @param {{ title?: string | null, kind_label?: string | null, occurred_on?: string | null } | null | undefined} record
 * @param {string} [today] YYYY-MM-DD
 * @returns {{ title: string, kindLabel: string, date: string } | null}
 */
export function schedulePromptFor(record, today = localToday()) {
  const date = String(record?.occurred_on ?? "");
  if (!ISO_DAY.test(date) || date < today) return null;
  const title = String(record?.title ?? "").trim();
  if (!title) return null;
  return { title, kindLabel: String(record?.kind_label ?? "").trim(), date };
}

/** 카드의 "일정에 넣기"를 눌렀을 때 채팅으로 보낼 문장. 날짜와 제목을 모두 담아 되묻지 않고 처리되게 한다. */
export function schedulePromptSentence({ title, date }) {
  return `방금 올린 "${title}" 문서의 날짜(${date})를 일정에 넣어줘`;
}
