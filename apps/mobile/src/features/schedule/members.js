import { relationText, shownName } from "../family-group/relations";

// 앱 안의 가족 id 규칙: 나는 "me", 관계가 엄마·아빠인 사람은 "mom"·"dad"(부모님 칩·이름표가 이 id 로 동작한다),
// 나머지는 서버 사용자 id 그대로. 같이(부탁) 등 아직 mock 인 기능과 id 가 맞도록 이 규칙을 유지한다.
export const ME = "me";

/**
 * 서버 가족 그룹(GET /family-group/groups/me)을 앱 구성원 목록과 id 변환기로 바꾼다.
 * 엄마·아빠 관계가 두 사람 이상이면 먼저 나온 사람만 "mom"·"dad" 로 두고 나머지는 사용자 id 를 쓴다.
 * @param {{ my_id?: string | null, members: { id: string, name: string, display_name?: string | null, family_relation?: string | null, family_relation_detail?: string | null }[] }} group
 * @returns {{ meUserId: string, members: import("./model").Member[], toApp: (userId: string) => string | null, toUser: (appId: string) => string | null }}
 */
export function buildFamily(group) {
  const meUserId = group.my_id ?? "";
  const taken = new Set();
  const appIdOf = new Map();
  const members = [];
  for (const m of group.members) {
    let appId = m.id;
    if (m.id === meUserId) appId = ME;
    else if ((m.family_relation === "mom" || m.family_relation === "dad") && !taken.has(m.family_relation)) {
      appId = m.family_relation;
      taken.add(appId);
    }
    appIdOf.set(m.id, appId);
    // 이름표는 관계(엄마·아빠…)가 있으면 그 말을, 없으면 표시 이름을 쓴다.
    members.push({
      id: appId,
      name: appId === ME ? "나" : relationText(m) || shownName(m),
      hasAccount: true,
    });
  }
  const userIdOf = new Map([...appIdOf].map(([userId, appId]) => [appId, userId]));
  return {
    meUserId,
    members: [...members.filter((m) => m.id === ME), ...members.filter((m) => m.id !== ME)],
    toApp: (userId) => appIdOf.get(userId) ?? null,
    toUser: (appId) => userIdOf.get(appId) ?? null,
  };
}
