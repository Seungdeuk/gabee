// 추천 카드 자리(추가 카드)에 보이는 문구와, 카드가 비었을 때 무엇을 보일지 정하는 순수 함수. 화면·테마에 의존하지 않아 node 테스트로 확인한다.

// 오늘 줄 추천을 다 보여 준 뒤 추가 카드에 남기는 마무리 문장. 하루 추천 개수 제한(15개)에 닿았을 때도 같은 문장을 쓴다.
export const SUGGESTIONS_DONE_TEXT = "오늘 추천은 여기까지, 내일도 챙겨 드릴게요💛";

// 오늘 호출을 다 썼는데 오늘 받은 추천이 하나도 없을 때(새로고침을 계속했거나 오류만 난 경우). 마무리 인사 대신 못 찾았다고 알린다.
export const SUGGESTIONS_SPENT_EMPTY_TEXT = "일정을 찾지 못했어요. 내일 다시 찾아볼게요😢";

// 추천 카드 자리가 비었을 때의 문장. 참고할 데이터가 없을 때(🌱)는 "추천드릴 게 없어요", 데이터는 있는데 AI 결과가 비었거나 걸러졌을 때는
// 없다고 하지 않고 "생각 중"이라고 한다(데이터가 있는데 없다고 하면 이상해서).
export const SUGGESTIONS_NO_DATA_TEXT = "지금은 추천드릴 게 없어요🌱";
export const SUGGESTIONS_FILTERED_TEXT = "어울리는 일정을 생각중이에요…";
// AI 호출이 오류로 끝났거나 추천을 못 불러왔을 때, 불러오는 동안의 문장.
export const SUGGESTIONS_PREPARING_TEXT = "아직 준비 중이에요⏳";
export const SUGGESTIONS_LOADING_TEXT = "어울리는 일정을 찾고 있어요…";

/**
 * 보여 줄 추천 카드가 하나도 없을 때 추가 카드 자리에 무엇을 보일지. 서버 상태(state)로 정한다:
 * exhausted(오늘 호출을 다 썼고 전부 확정) → 마무리 문장, no_data → 🌱, filtered → "생각중이에요…", preparing 이나 불러오기 실패 → 준비 중 ⏳.
 * refresh 는 새로고침 버튼을 보일지(오늘 호출이 남았고 곧 풀릴 수 있을 때만).
 * @param {{ loading: boolean, loaded: boolean, state?: string, failed?: boolean, canRefresh?: boolean }} server
 * @returns {{ kind: "loading" } | { kind: "message", text: string, refresh: boolean }}
 */
export function emptySlotView(server) {
  if (server.loading || !server.loaded) return { kind: "loading" };
  if (server.failed) return { kind: "message", text: SUGGESTIONS_PREPARING_TEXT, refresh: true };
  switch (server.state) {
    case "no_data":
      return { kind: "message", text: SUGGESTIONS_NO_DATA_TEXT, refresh: server.canRefresh !== false };
    case "filtered":
      return { kind: "message", text: SUGGESTIONS_FILTERED_TEXT, refresh: server.canRefresh !== false };
    case "spent_empty":
      return { kind: "message", text: SUGGESTIONS_SPENT_EMPTY_TEXT, refresh: false };
    case "preparing":
      return { kind: "message", text: SUGGESTIONS_PREPARING_TEXT, refresh: server.canRefresh !== false };
    default:
      return { kind: "message", text: SUGGESTIONS_DONE_TEXT, refresh: false };
  }
}
