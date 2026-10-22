import { KIND } from "./constants";
import { compareItems } from "./model";

// 챙길 것은 에이전트가 오늘 일정에서 유추해 묻는 내용(예: 여행이 있으면 여권)이라, 서버가 붙기 전까지 임시 문장이다.
export const MOCK_CARRY = [{ id: "passport", text: "11월 3일 제주 여행, 여권 챙기셨어요?" }];
export const MOCK_ADD = { id: "add", text: "관리비 납부 일정을 추가해 드릴까요?" };

const byTime = (a, b) => (a.startTime ?? "99:99").localeCompare(b.startTime ?? "99:99");

/**
 * 약속 확인 카드. 오늘 약속 중 아직 확인하지 않은 것을 시간 빠른 순으로 하나 묻는다.
 * 하나도 확인하지 않았으면 안내 문장만, 전부 확인했으면 완료 문장을 남기고, 오늘 약속이 없으면 null(카드 숨김).
 * @param {import("./model").ScheduleItem[]} items 전체 항목
 * @param {string} today "YYYY-MM-DD"
 * @param {string[]} skippedIds 새로고침 때 "나중에"로 건너뛸 항목 id
 * @returns {{ text: string, itemId?: string, label?: string } | null}
 */
export function pickAppointmentCard(items, today, skippedIds = []) {
  const todays = items.filter((i) => i.kind === KIND.appointment && i.date === today).sort(compareItems);
  if (todays.length === 0) return null;
  const rest = todays.filter((i) => !i.checked);
  if (rest.length === 0) return { text: "오늘 약속을 모두 확인했어요" };
  if (rest.length === todays.length) return { text: "오늘 약속 체크해주세요" };
  const sorted = [...rest].sort(byTime);
  const next = sorted.find((i) => !skippedIds.includes(i.id)) ?? sorted[0];
  return { itemId: next.id, text: `${next.title} 기억하고 계시지요?`, label: "기억해요" };
}

/**
 * 할 일 확인 카드. 오늘 할 일과 에이전트가 권하는 챙길 것을 함께 다룬다.
 * 챙길 것은 바로 구체적으로 묻고, 전부 끝내도 "오늘 할 일을 모두 확인했어요"를 남긴다.
 * @param {import("./model").ScheduleItem[]} items 전체 항목
 * @param {string} today "YYYY-MM-DD"
 * @param {{ id: string, text: string }[]} carry 챙길 것 후보
 * @param {string[]} carryDoneIds "챙겼어요"를 누른 챙길 것 id
 * @param {string[]} skippedIds 새로고침 때 "나중에"로 건너뛸 id (할 일·챙길 것 공통)
 * @returns {{ text: string, target?: { type: "todo" | "carry", id: string }, label?: string, laterLabel?: string } | null}
 */
export function pickTodoCard(items, today, carry, carryDoneIds = [], skippedIds = []) {
  const todos = items.filter((i) => i.kind === KIND.todo && i.date === today);
  const total = todos.length + carry.length;
  if (total === 0) return null;

  const pending = [
    ...todos.filter((i) => !i.checked).sort(byTime).map((i) => ({ type: "todo", id: i.id, text: `${i.title} 하셨어요?`, label: "했어요", laterLabel: "나중에" })),
    ...carry
      .filter((c) => !carryDoneIds.includes(c.id))
      .map((c) => ({ type: "carry", id: c.id, text: c.text, label: "챙겼어요", laterLabel: "아직이요" })),
  ];
  if (pending.length === 0) return { text: "오늘 할 일을 모두 확인했어요" };
  const next = pending.find((p) => !skippedIds.includes(p.id)) ?? pending[0];
  return { target: { type: next.type, id: next.id }, text: next.text, label: next.label, laterLabel: next.laterLabel };
}
