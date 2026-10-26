/**
 * 가족 관계(엄마·아빠·…·기타)와 구성원 이름 표시 규칙. 서버(app/features/family_group)의 관계 값과 같다.
 */
export const RELATIONS = [
  { key: "mom", label: "엄마" },
  { key: "dad", label: "아빠" },
  { key: "son", label: "아들" },
  { key: "daughter", label: "딸" },
  { key: "grandma", label: "할머니" },
  { key: "grandpa", label: "할아버지" },
  { key: "other", label: "기타" },
];

export const DETAIL_MAX = 40;

/**
 * 관계를 사용자 문구로. 기타이면 직접 적은 관계(없으면 "기타"), 정해지지 않았으면 "".
 * @param {{ family_relation?: string | null, family_relation_detail?: string | null } | null | undefined} member
 * @returns {string}
 */
export function relationText(member) {
  const key = member?.family_relation;
  if (!key) return "";
  if (key === "other") return member.family_relation_detail || "기타";
  return RELATIONS.find((r) => r.key === key)?.label ?? "";
}

/**
 * 화면에 보일 이름: 내가 붙인 별명 > 그 가족에서 쓰는 표시 이름 > 계정 이름.
 * @param {{ name: string, display_name?: string | null }} member
 * @param {{ nickname?: string | null } | undefined} nickname 내가 이 사람에게 붙인 별명
 * @returns {string}
 */
export const shownName = (member, nickname) => nickname?.nickname || member.display_name || member.name;
