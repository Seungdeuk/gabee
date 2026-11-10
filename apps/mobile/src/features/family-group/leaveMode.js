/**
 * 가족 나가기 방식: 구성원은 그냥 나간다("member"). 소유자는 다른 구성원이 있으면 나갈 수 없고("blocked"),
 * 나 혼자일 때만 가족의 모든 데이터를 지우고 나간다("last", 되돌릴 수 없다).
 * @param {{ isOwner: boolean, memberCount: number }} options memberCount 는 나를 포함한 구성원 수
 * @returns {"member" | "blocked" | "last"}
 */
export function leaveMode({ isOwner, memberCount }) {
  if (!isOwner) return "member";
  return memberCount > 1 ? "blocked" : "last";
}
