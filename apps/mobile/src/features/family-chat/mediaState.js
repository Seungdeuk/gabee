// 모음 불러오기 상태 전이(순수 함수). 훅(useChatMedia)은 요청만 보내고, 어떤 응답을 받아들일지는 여기서 정한다.
import { mediaErrorMessage, mergeMedia, normalizeCounts } from "./mediaUtils";

/**
 * 처음 상태. seq 는 "지금 유효한 요청 번호"다 — 이 번호가 아닌 응답은 버려진다.
 * @returns {{ seq: number, items: object[], next: number | null, status: "loading" | "ready" | "error", error: string, loadingMore: boolean, counts: { image: number, file: number, video: number } }}
 */
export const initialMediaState = () => ({ seq: 0, items: [], next: null, status: "loading", error: "", loadingMore: false, counts: normalizeCounts(null) });

/**
 * 상태 전이. 동작:
 * - start: kind·방이 바뀌었거나 다시 시도할 때. 번호를 올리고 목록을 비워 로딩으로 돌아간다(옛 요청의 응답은 번호가 달라 무시된다). counts 는 탭 글자를 위해 남긴다.
 * - firstOk / firstFail: 첫 쪽 결과(seq 가 맞을 때만).
 * - moreStart: 다음 쪽 요청 시작(오류 문구를 지운다).
 * - moreOk / moreFail: 다음 쪽 결과. 실패해도 이미 받은 목록은 그대로 두고 오류 문구만 남긴다.
 * @param {ReturnType<typeof initialMediaState>} state
 * @param {{ type: string, seq?: number, page?: { items?: object[], next_before_id?: number | null, counts?: object }, error?: { status?: number } }} action
 * @returns {ReturnType<typeof initialMediaState>}
 */
export function mediaReducer(state, action) {
  if (action.type === "start") return { ...initialMediaState(), seq: action.seq, counts: state.counts };
  if (action.seq !== state.seq) return state; // 옛 요청의 응답
  switch (action.type) {
    case "firstOk":
      return { ...state, items: action.page.items ?? [], next: action.page.next_before_id ?? null, status: "ready", error: "", loadingMore: false, counts: normalizeCounts(action.page.counts) };
    case "firstFail":
      return { ...state, items: [], next: null, status: "error", error: mediaErrorMessage(action.error), loadingMore: false };
    case "moreStart":
      return { ...state, loadingMore: true, error: "" };
    case "moreOk":
      return { ...state, items: mergeMedia(state.items, action.page.items), next: action.page.next_before_id ?? null, loadingMore: false, counts: normalizeCounts(action.page.counts) };
    case "moreFail":
      return { ...state, loadingMore: false, error: mediaErrorMessage(action.error) };
    default:
      return state;
  }
}

/**
 * 다음 쪽을 요청해도 되는지: 첫 쪽을 받았고, 이어 받을 커서가 있고, 받는 중이 아닐 때. 이전 쪽 실패 뒤에도 "다시 시도"로 요청할 수 있다.
 * @param {ReturnType<typeof initialMediaState>} state
 * @returns {boolean}
 */
export const canLoadMore = (state) => state.status === "ready" && state.next != null && !state.loadingMore;
