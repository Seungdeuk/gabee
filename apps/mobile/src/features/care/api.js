import { apiFetch } from "@/shared/api/client";
import { loadNicknames } from "@/shared/members/nicknames";

/**
 * 돌봄 서버 호출. 데일리 체크(항목·기록·추천·식단) 호출은 지갑 탭 개편 때 지웠고, 위치 공유(지금은 보류)만 남아 있다.
 * 응답 모양은 docs/contracts/openapi.json 의 /care/* 를 따른다.
 */

/**
 * 위치 공유(개인정보). 동의한 사람만 위치를 보낼 수 있고, 가족 구성원만 볼 수 있다.
 * @typedef {{ consent: boolean, since: string | null }} Consent
 * @typedef {{ lat: number, lng: number, accuracy_m: number | null, recorded_at: string }} LocationPoint
 * @typedef {{ user_id: string, name: string, is_me: boolean, sharing: boolean, lat: number | null, lng: number | null, accuracy_m: number | null, recorded_at: string | null, minutes_ago: number | null }} MemberLocation
 */

/** 내 위치 공유 동의 상태. @returns {Promise<Consent>} */
export const getLocationConsent = () => apiFetch("/care/location/consent");

/** 동의하거나 철회한다. 철회하면 서버가 저장된 내 위치를 바로 지운다. @param {boolean} consent @returns {Promise<Consent>} */
export const setLocationConsent = (consent) => apiFetch("/care/location/consent", { method: "PUT", body: { consent } });

/** 위치를 보낸다(동의하지 않았으면 서버가 403 consent_required 로 거절). @param {LocationPoint[]} points @returns {Promise<{ saved: number, skipped: number }>} */
export const sendLocations = (points) => apiFetch("/care/locations", { method: "POST", body: { points } });

/** 가족 구성원의 최신 위치(이름은 내가 붙인 별명이 있으면 별명). 동의하지 않은 사람은 좌표 없이 sharing=false 로 온다. @returns {Promise<{ members: MemberLocation[], retention_days: number }>} */
export async function getLatestLocations() {
  const [latest, byId] = await Promise.all([apiFetch("/care/locations/latest"), loadNicknames()]);
  return { ...latest, members: latest.members.map((m) => (byId[m.user_id] && !m.is_me ? { ...m, name: byId[m.user_id] } : m)) };
}
