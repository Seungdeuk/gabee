// 보낸 부탁의 "받는 사람 바꾸기" 시트 규칙. 화면에 의존하지 않아 node 테스트로 확인한다.

const sameSet = (a, b) => a.length === b.length && a.every((id) => b.includes(id));

/**
 * 시트의 칩 줄 나누기: 위 줄은 지금 받는 사람 중 수락한 사람, 아래 줄은 나머지.
 * @param {{ id: string }[]} candidates 고를 수 있는 사람(계정 있는 가족, 나 제외)
 * @param {string[]} current 지금 받는 사람 id
 * @param {Record<string, "accepted" | "declined">} replies
 */
export function splitChips(candidates, current, replies) {
  const accepted = (m) => current.includes(m.id) && replies[m.id] === "accepted";
  return { accepted: candidates.filter(accepted), others: candidates.filter((m) => !accepted(m)) };
}

/**
 * 고른 사람(draft)에 따른 안내 문구와 저장 가능 여부. 아무도 안 골랐거나 바뀐 게 없으면 저장할 수 없다.
 * @param {string[]} current 지금 받는 사람 id
 * @param {Record<string, "accepted" | "declined">} replies
 * @param {string[]} draft 시트에서 고른 사람 id
 * @returns {{ message: string | null, canSave: boolean }}
 */
export function sheetGuide(current, replies, draft) {
  if (draft.length === 0) return { message: "한 명 이상 골라 주세요. 모두 빼려면 부탁을 취소해 주세요", canSave: false };
  const removed = current.filter((id) => !draft.includes(id));
  const canSave = !sameSet(current, draft);
  if (removed.some((id) => replies[id] === "accepted")) return { message: "수락한 분을 제외하면 그 일정도 같이 사라져요", canSave };
  if (removed.length > 0) return { message: "제외한 분은 이 부탁을 더 볼 수 없어요", canSave };
  return { message: null, canSave };
}

/** 부탁 취소 확인 팝업의 본문. 수락한 사람이 있을 때만 일정 삭제 안내를 넣는다. */
export function cancelMessage(hasAccepted) {
  return [hasAccepted ? "취소하면 수락하신 분이 만든 일정도 같이 사라져요." : null, "받는 분께는 알림이 가지 않아요."].filter(Boolean).join("\n");
}
