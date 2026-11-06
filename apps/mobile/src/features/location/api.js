import { apiFetch } from "@/shared/api/client";

/**
 * 위치 공유(베타) 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /location/* 를 따른다.
 * @typedef {{ center_lat: number, center_lng: number, radius_m: number, sample_count: number, computed_at: string }} Zone
 * @typedef {{ enabled: boolean, consent: boolean, paused_until: string | null, paused: boolean, zone: Zone | null, point_count: number }} MyLocation
 * @typedef {{ saved: boolean, reason: "paused" | "no_consent" | null, outside: boolean, alerted: boolean }} PointSaved
 * @typedef {{ user_id: string, name: string, is_me: boolean, sharing: boolean, paused: boolean, lat: number | null, lng: number | null, recorded_at: string | null, outside: boolean, zone: Zone | null }} MemberLocation
 * @typedef {{ members: MemberLocation[], can_see_family: boolean }} FamilyLocations
 */

/** @returns {Promise<MyLocation>} */
export const getMyLocation = () => apiFetch("/location/me");

/** 동의(켜기)와 철회. 철회하면 서버에 저장된 내 위치가 모두 지워진다. @param {boolean} consent @returns {Promise<MyLocation>} */
export const setLocationConsent = (consent) => apiFetch("/location/consent", { method: "PUT", body: { consent } });

/** 저장된 내 위치·활동 구역·설정을 지운다(동의 상태는 그대로). @returns {Promise<MyLocation>} */
export const deleteMyLocation = () => apiFetch("/location/me", { method: "DELETE" });

/** 여행 등으로 위치 공유를 잠시 멈춘다(1~14일). days 가 없으면 다시 켠다. @param {number | null} days @returns {Promise<MyLocation>} */
export const setLocationPause = (days) => apiFetch("/location/pause", { method: "PUT", body: days ? { days } : {} });

/** 내 위치 하나를 올린다. 구역 밖이면 서버가 부모에게 알린다. @param {{ lat: number, lng: number, accuracy_m?: number | null }} point @returns {Promise<PointSaved>} */
export const postLocationPoint = (point) => apiFetch("/location/points", { method: "POST", body: point });

/** @returns {Promise<FamilyLocations>} */
export const getFamilyLocations = () => apiFetch("/location/family");

/** 시연용: 활동 구역을 벗어난 것처럼 판정만 한다(위치는 저장하지 않는다). @param {number} [distance] @returns {Promise<PointSaved>} */
export const simulateExit = (distance = 5000) => apiFetch("/location/simulate-exit", { method: "POST", body: { distance_m: distance } });
