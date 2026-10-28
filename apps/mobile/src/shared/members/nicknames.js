import { apiFetch } from "@/shared/api/client";

/**
 * 내가 가족에게 붙인 별명을 구성원 id 별로 모은다. 별명이 없는 사람은 넣지 않는다.
 * @param {{ target_user_id: string, nickname?: string | null }[] | null | undefined} rows 서버 GET /family-group/groups/me/nicknames 응답
 * @returns {Record<string, string>}
 */
export function nicknameById(rows) {
  const map = {};
  for (const row of Array.isArray(rows) ? rows : []) {
    const nickname = String(row?.nickname ?? "").trim();
    if (row?.target_user_id && nickname) map[row.target_user_id] = nickname;
  }
  return map;
}

/**
 * 구성원 목록에 별명을 입힌다. 별명이 있는 사람은 display_name 을 별명으로 바꾸고 nickname 에도 넣는다(원래 표시 이름은 가려진다).
 * 이름을 `display_name || name` 으로 읽는 기존 화면이 고치지 않아도 별명을 보여 주도록 하기 위해서다. 별명은 보는 사람 본인에게만 적용된다.
 * @template {{ id: string, display_name?: string | null }} M
 * @param {M[] | null | undefined} members
 * @param {Record<string, string>} byId nicknameById 결과
 * @returns {(M & { nickname?: string })[]}
 */
export function withNicknames(members, byId) {
  return (Array.isArray(members) ? members : []).map((m) => (byId[m.id] ? { ...m, display_name: byId[m.id], nickname: byId[m.id] } : m));
}

/**
 * 내가 붙인 별명(구성원 id → 별명). 불러오지 못하면 빈 값이라 화면은 별명 없이 원래 이름으로 보인다.
 * @returns {Promise<Record<string, string>>}
 */
export async function loadNicknames() {
  try {
    return nicknameById(await apiFetch("/family-group/groups/me/nicknames"));
  } catch {
    return {};
  }
}

/**
 * 내 가족 그룹(이름·구성원·내 id)을 불러오고 구성원에 내가 붙인 별명을 입힌다. 그룹이 없으면 404 오류가 그대로 난다.
 * @returns {Promise<{ id: string, name: string, my_id: string | null, members: { id: string, name: string, display_name?: string | null, nickname?: string, photo_url?: string | null }[] }>}
 */
export async function getGroupWithNicknames() {
  const [group, byId] = await Promise.all([apiFetch("/family-group/groups/me"), loadNicknames()]);
  return { ...group, members: withNicknames(group.members, byId) };
}
