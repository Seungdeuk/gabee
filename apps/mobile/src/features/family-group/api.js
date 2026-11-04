import { apiFetch, setToken } from "@/shared/api/client";

import { photoFileName, photoMimeType } from "./photo";

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

/** 내 가족 그룹과 구성원 목록. */
export const getMyGroup = () => apiFetch("/family-group/groups/me");

/**
 * 초대 코드로 참여를 신청한다. 모든 계정(익명 포함)에 승인 대기 요청(status: "pending")이 온다. 관리자가 승인해야 구성원이 된다.
 * @param {string} code
 * @returns {Promise<{ status: "pending", id: string, group_id: string, group_name: string }>}
 */
export const requestJoin = (code) => apiFetch("/family-group/groups/join", { method: "POST", body: { code } });

/** 내가 낸 가장 최근 가입 요청(없으면 null). status: pending | approved | rejected | cancelled */
export const getMyJoinRequest = () => apiFetch("/family-group/groups/join-requests/mine");

/** 내 대기 요청을 취소한다. */
export const cancelJoinRequest = (id) => apiFetch(`/family-group/groups/join-requests/${id}/cancel`, { method: "POST" });

/** 내가 이 가족에서 나간다(204, 본문 없음 — apiFetch 가 null 로 돌려준다). 소유자는 나갈 수 없다(cannot_leave_owner). */
export const leaveFamily = () => apiFetch("/family-group/groups/me/leave", { method: "POST" });

/**
 * 가족 이름을 바꾼다(1~60자). 가족 관리자(소유자·관리자)만, 일반 구성원은 403 not_manager.
 * @param {string} name 새 가족 이름
 * @returns {Promise<object>} 바뀐 GroupOut
 */
export const renameFamily = (name) => apiFetch("/family-group/groups/me/name", { method: "PUT", body: { name } });

/** 새 초대 코드를 만든다(기본 24시간·20명, 기존 코드는 폐기). 가족 관리자만. */
export const reissueInvite = () => apiFetch("/family-group/groups/invites/reissue", { method: "POST" });

/** 초대 코드로 들어온 사람을 승인 없이 바로 구성원으로 넣을지 켜고 끈다. 가족 관리자만. */
export const setInviteAutoApprove = (autoApprove) =>
  apiFetch("/family-group/groups/invites/settings", { method: "PUT", body: { auto_approve: autoApprove } });

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


/**
 * 내 프로필 사진을 올린다(POST /family-group/me/photo, multipart 'file'). 서버가 512px 정사각형 JPEG 로 다시 만든다.
 * 웹은 asset.file(없으면 asset.uri 의 blob)을 그대로, 네이티브는 {uri, name, type} 으로 보낸다. Content-Type 은 fetch 가 boundary 와 함께 붙인다.
 * @param {{ uri: string, file?: Blob, fileName?: string | null, mimeType?: string }} asset expo-image-picker 가 돌려준 asset
 * @returns {Promise<{ photo_url: string | null, photo_updated_at: string | null }>}
 */
export async function uploadMyPhoto(asset) {
  const name = photoFileName(asset);
  const type = photoMimeType(asset);
  const form = new FormData();
  if (asset.file) {
    form.append("file", asset.file, name);
  } else if (/^(blob|data):/.test(asset.uri)) {
    const blob = await (await fetch(asset.uri)).blob();
    form.append("file", blob, name);
  } else {
    form.append("file", { uri: asset.uri, name, type });
  }
  return apiFetch("/family-group/me/photo", { method: "POST", body: form });
}

/** 내 프로필 사진을 지운다(없어도 성공). */
export const deleteMyPhoto = () => apiFetch("/family-group/me/photo", { method: "DELETE" });
