import { apiFetch, setToken } from "@/shared/api/client";

/**
 * 이름·역할로 가입하고 토큰을 기억한다.
 * @param {string} name
 * @param {"parent" | "child" | "other"} role
 * @returns {Promise<{ user: { id: string, name: string, role: string, active_group_id: string | null }, token: string }>}
 */
export async function signup(name, role = "child") {
  const res = await apiFetch("/family-group/users", { method: "POST", body: { name, role } });
  setToken(res.token);
  return res;
}

/** 가족 그룹을 만든다. 응답에 초대 코드(invite_code)가 들어 있다. */
export const createGroup = (name) => apiFetch("/family-group/groups", { method: "POST", body: { name } });

/** 초대 코드로 가족 그룹에 참여한다. */
export const joinGroup = (code) => apiFetch("/family-group/groups/join", { method: "POST", body: { code } });

/** 내 가족 그룹과 구성원 목록. */
export const getMyGroup = () => apiFetch("/family-group/groups/me");
