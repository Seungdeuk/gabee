// 찰칵! 탐정단 가비 추천을 화면에 옮기는 순수 함수(화면 밖에서 시험한다: tests/playphotorecscreen.test.js)
const ZOOMS = [4, 6, 8, 16, 32]; // 서버(play_photos)와 같은 확대 배율 한도
const DEFAULT_ZOOM = 8;

/** 카드 위 알약 글자: 가족 사진인지 흔한 사진인지 */
export const photoRecLabel = (item) => (item.source === "album" ? "가족 사진" : "가비가 고른 사진");

export const REC_UNAVAILABLE_NOTE = "이 사진은 지금 쓸 수 없어요, 다른 추천을 골라 주세요";

/** 사진을 못 쓰는 추천을 보냈을 때의 서버 오류인지(409 photo_not_available · rec_already_sent) */
export const isRecUnavailable = (e) => e?.status === 409 && (e?.code === "photo_not_available" || e?.code === "rec_already_sent");

/**
 * "이 문제로 쓰기"를 눌렀을 때 만들 화면 상태. photo 가 사진 상태의 전부이므로(recId 도 여기에만 있다) 사진을 다른 것으로 바꾸면 recId 가 함께 사라진다.
 * @param {{ id: string, question: string, options: string[], answer_index: number, box_x: number, box_y: number, zoom: number, image_url?: string }} item
 */
export function recToDraft(item) {
  const options = (item.options ?? []).slice(0, 4);
  while (options.length < 2) options.push("");
  const answer = item.answer_index;
  return {
    photo: { kind: "rec", recId: item.id, imageUrl: item.image_url ?? null, boxX: item.box_x, boxY: item.box_y },
    zoom: ZOOMS.includes(item.zoom) ? item.zoom : DEFAULT_ZOOM,
    question: item.question ?? "",
    count: options.length,
    opts: [...options, "", "", "", ""].slice(0, 4),
    ansIdx: Number.isInteger(answer) && answer >= 0 && answer < options.length ? answer : null,
  };
}

/**
 * 보낼 사진 부분. 추천 카드(kind "rec")만 recId 를 보내고(파일 없이), 내 폰 사진은 파일과 source 2 만 보낸다.
 * 서버는 file 과 rec_id 가 같이 오면 file 을 우선해 출처를 내 폰으로 보므로, 사진이 추천이 아니면 recId 를 절대 담지 않는다.
 * 고른 사진이 없거나(none) 가족 앨범 시안(album)이면 null.
 * @param {{ kind: string, recId?: string, asset?: object } | null | undefined} photo
 * @returns {{ recId: string } | { image: object, source: 2 } | null}
 */
export function photoSendPart(photo) {
  if (photo?.kind === "rec" && photo.recId) return { recId: photo.recId };
  if (photo?.kind === "phone" && photo.asset) return { image: photo.asset, source: 2 };
  return null;
}

/**
 * 탭에 맞는 보낼 사진 부분. 가비 추천 탭은 추천 카드(kind "rec")만, 직접 내기 탭은 내 폰 사진(kind "phone")만 보낸다.
 * 두 탭의 사진 상태는 따로 있지만, 한쪽의 recId 가 다른 쪽 보내기로 새지 않게 여기서 한 번 더 막는다.
 * @param {"rec" | "manual"} mode
 * @param {{ kind: string } | null | undefined} photo
 */
export function photoSendPartFor(mode, photo) {
  if (mode === "rec") return photo?.kind === "rec" ? photoSendPart(photo) : null;
  return photo?.kind === "phone" ? photoSendPart(photo) : null;
}

/** 추천 탭 초안을 비운 상태(사진 없음): 못 쓰는 추천을 보냈을 때 되돌리는 값 */
export const EMPTY_REC_PHOTO = { kind: "none" };

/**
 * 가비 추천 탭에서 고른 카드로 고치는 칸(초안)에 채울 값. 직접 내기 초안은 건드리지 않는다.
 * pickedId 는 "이 문제로 쓰기"를 마지막으로 누른 카드, ask 는 질문 종류 칩(직접 쓰기).
 */
export function recDraftFromItem(item) {
  const d = recToDraft(item);
  return { ...d, ask: "직접 쓰기", pickedId: item.id, withNote: true, note: "" };
}

/** 두 초안 중 지금 탭의 것을 고른다 */
export const activeDraft = (mode, recDraft, manualDraft) => (mode === "rec" ? recDraft : manualDraft);
