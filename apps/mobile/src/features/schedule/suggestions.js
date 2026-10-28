import { KIND } from "./constants";
import { compareItems } from "./model";

// 내 약속·할 일에 없는 추천(추가 카드). 서버가 붙기 전까지 임시 문장이다.
// name 은 카드 문장에 쓰는 줄인 이름(관련 일정이 있으면 함께 적음), draft 는 "추가"를 눌렀을 때 등록 화면에 미리 채울 내용이다.
// 등록 화면은 draft.kind(약속·할 일)로 열리고, 카드 문장은 형태를 구분하지 않고 "일정으로 추가해 드릴까요?"로 통일한다.
export const MOCK_SUGGESTIONS = [
  { id: "passport", name: "제주 여행 여권 챙기기", draft: { kind: KIND.todo, title: "여권 챙기기", daysFromToday: 10 } },
  { id: "add-todo", name: "관리비 납부", draft: { kind: KIND.todo, title: "관리비 납부", daysFromToday: 6 } },
  { id: "add-appointment", name: "정기 검진", draft: { kind: KIND.appointment, title: "정기 검진", daysFromToday: 14 } },
];

// 오늘 줄 추천을 다 보여 준 뒤 추가 카드에 남기는 마무리 문장. 하루 추천 개수 제한(15개)에 닿았을 때도 같은 문장을 쓴다.
export const SUGGESTIONS_DONE_TEXT = "오늘 추천은 여기까지, 내일도 챙겨 드릴게요 💛";

/**
 * 확인 카드 하나. 내 약속·할 일 중 오늘 것을 한 장에서 하나씩 묻는다: 약속 먼저(시간 빠른 순), 그다음 할 일.
 * 확인하면 다음 항목으로 바뀌고, 카드의 새로고침(cursor 를 하나 올림)은 확인하지 않고 다른 항목을 보여 준다.
 * 전부 확인했거나 오늘 일정이 없으면 "오늘 일정을 모두 확인했어요 👏"를 남긴다(카드 자리는 항상 보인다).
 * @param {import("./model").ScheduleItem[]} items 전체 항목
 * @param {string} today "YYYY-MM-DD"
 * @param {number} cursor 새로고침 횟수. 확인할 항목이 남은 개수로 돌려 가며 보여 준다
 * @returns {{ text: string, count: number, target?: { type: "item", id: string }, label?: string, laterLabel?: string }}
 */
export function pickCheckCard(items, today, cursor = 0) {
  const todays = items.filter((i) => i.date === today).sort(compareItems);

  const pending = todays.filter((i) => !i.checked);
  if (pending.length === 0) return { text: "오늘 일정을 모두 확인했어요 👏", count: 0 };
  const next = pending[cursor % pending.length];
  const appointment = next.kind === KIND.appointment;
  return {
    target: { type: "item", id: next.id },
    text: appointment ? `${next.title} 기억하고 계시지요?` : `${next.title} 하셨어요?`,
    label: appointment ? "기억해요" : "했어요",
    laterLabel: "나중에",
    count: pending.length,
  };
}
