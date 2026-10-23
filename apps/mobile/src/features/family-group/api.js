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

/**
 * 초대 코드로 참여한다. 정식 회원은 승인 대기 요청({ status: "pending", ... })이, 기존 익명 계정은 바로 GroupOut 이 온다.
 * @param {string} code
 * @returns {Promise<{ status: "pending", id: string, group_name: string } | { id: string, name: string, members: object[] }>}
 */
export const requestJoin = (code) => apiFetch("/family-group/groups/join", { method: "POST", body: { code } });

/** 내가 낸 가장 최근 가입 요청(없으면 null). status: pending | approved | rejected | cancelled */
export const getMyJoinRequest = () => apiFetch("/family-group/groups/join-requests/mine");

/** 내 대기 요청을 취소한다. */
export const cancelJoinRequest = (id) => apiFetch(`/family-group/groups/join-requests/${id}/cancel`, { method: "POST" });

/** 새 초대 코드를 만든다(24시간·1회, 기존 코드는 폐기). 가족 관리자만. */
export const reissueInvite = () => apiFetch("/family-group/groups/invites/reissue", { method: "POST" });

/** 지금 쓸 수 있는 초대 코드를 모두 폐기한다. 가족 관리자만. */
export const revokeInvite = () => apiFetch("/family-group/groups/invites/revoke", { method: "POST" });

/** 승인 대기 중인 가입 요청 목록. 가족 관리자만. */
export const listJoinRequests = () => apiFetch("/family-group/groups/me/join-requests");

/** 가입 요청을 승인한다(승인된 사람은 구성원이 된다). 가족 관리자만. */
export const approveJoinRequest = (id) =>
  apiFetch(`/family-group/groups/join-requests/${id}/approve`, { method: "POST" });

/** 가입 요청을 거절한다. 가족 관리자만. */
export const rejectJoinRequest = (id) => apiFetch(`/family-group/groups/join-requests/${id}/reject`, { method: "POST" });

/**
 * 내 가족 프로필(표시 이름·관계)을 바꾼다. 보낸 항목만 바뀌고 null 은 지운다. 응답은 갱신된 GroupOut.
 * @param {{ display_name?: string | null, family_relation?: string | null, family_relation_detail?: string | null }} fields
 */
export const updateMyProfile = (fields) => apiFetch("/family-group/groups/me/profile", { method: "PUT", body: fields });

/** 구성원을 관리자로 지정하거나("admin") 구성원으로 되돌린다("member"). 가족 소유자만. */
export const setMemberRole = (userId, role) =>
  apiFetch(`/family-group/groups/members/${userId}/role`, { method: "PUT", body: { role } });

/** 내가 다른 구성원에게 붙인 별명·메모(내가 쓴 것만). */
export const listNicknames = () => apiFetch("/family-group/groups/me/nicknames");

/** 별명·메모를 정한다. 둘 다 비우면 지워진다. 나에게만 보인다. */
export const setNickname = (userId, { nickname, memo }) =>
  apiFetch(`/family-group/groups/me/nicknames/${userId}`, { method: "PUT", body: { nickname: nickname || null, memo: memo || null } });

