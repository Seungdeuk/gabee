import { KIND } from "./constants";
import { compareItems } from "./model";
import { weekOf } from "./utils/date";

// 서버(일정 에이전트)가 붙기 전까지 쓰는 임시 답변 만들기. 말에 들어 있는 낱말로 답을 고르고, 서버가 붙으면 이 파일의 함수 본문만 api 호출로 바꾼다.
// 에이전트는 일정을 직접 저장·수정·삭제하지 않는다. 바꾸고 싶으면 제안 카드로 등록 화면을 열어 사용자가 확인 후 저장한다.

/** 입력창 위 빠른 질문 칩. 누르면 이 문장이 바로 전송된다. */
export const QUICK_QUESTIONS = ["우선순위 정해줘", "빈 시간 찾아줘", "이번 주 일정 알려줘"];

/** 답을 만들지 못했을 때의 안내 문장. */
export const ERROR_TEXT = "지금은 답하기 어려워요. 잠시 뒤에 다시 물어봐 주세요";

/**
 * @typedef {Object} AgentAnswer
 * @property {string} text 답 문장
 * @property {import("./model").ScheduleItem[]} [items] 답에 붙이는 약속·할 일 미니 카드
 * @property {{ name: string, draft: { kind: "appointment" | "todo", title: string, daysFromToday: number } }} [suggestion] 추가해 드릴까요? 제안
 * @property {boolean} [error] 답하지 못했다
 */

/**
 * 질문에 대한 임시 답. "오류"나 "에러"가 들어 있으면 답하지 못한 것으로 돌려 오류 안내를 확인할 수 있게 한다.
 * @param {string} question
 * @param {import("./model").ScheduleItem[]} items 전체 항목
 * @param {string} today "YYYY-MM-DD"
 * @returns {AgentAnswer}
 */
export function answerFor(question, items, today) {
  const week = weekOf(today);
  const thisWeek = items.filter((i) => week.includes(i.date)).sort((a, b) => a.date.localeCompare(b.date) || compareItems(a, b));

  if (/오류|에러/.test(question)) return { text: ERROR_TEXT, error: true };

  if (question.includes("병원")) {
    const found = thisWeek.filter((i) => i.topicId === "hospital");
    return found.length > 0
      ? { text: `이번 주 병원 관련은 ${found.length}개예요.`, items: found }
      : { text: "이번 주 병원 관련 일정은 없어요." };
  }
  if (question.includes("빈 시간")) {
    return {
      text: "내일 오후 2시부터 5시까지 비어 있어요. 병원에 다녀온 뒤 약을 타 오는 건 어때요?",
      suggestion: { name: "약 타 오기", draft: { kind: KIND.todo, title: "약 타 오기", daysFromToday: 1 } },
    };
  }
  if (question.includes("우선순위")) {
    const todays = items.filter((i) => i.date === today && !i.checked).sort(compareItems);
    return todays.length > 0
      ? { text: "오늘은 이 순서로 챙기시면 좋겠어요.", items: todays }
      : { text: "오늘 챙길 일은 모두 끝났어요. 수고하셨어요." };
  }
  if (question.includes("일정")) {
    return thisWeek.length > 0
      ? {
          text: thisWeek.length > 5 ? `이번 주 일정은 ${thisWeek.length}개예요. 가까운 5개를 보여 드릴게요.` : `이번 주 일정은 ${thisWeek.length}개예요.`,
          items: thisWeek.slice(0, 5),
        }
      : { text: "이번 주에는 등록된 일정이 없어요." };
  }
  return { text: "아직 그건 잘 몰라요. 일정에 대해 물어봐 주세요." };
}
