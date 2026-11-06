import { apiFetch } from "@/shared/api/client";

/**
 * 위치 공유(베타) 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /location/* 를 따른다.
 * @typedef {{ center_lat: number, center_lng: number, radius_m: number, sample_count: number, computed_at: string }} Zone
 * @typedef {{ enabled: boolean, consent: boolean, paused_until: string | null, paused: boolean, background: boolean, zone: Zone | null, point_count: number }} MyLocation
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

/** 앱이 꺼져 있어도 위치를 모으는 것에 동의(true)하거나 끈다. 위치 공유에 먼저 동의해야 켤 수 있다. @param {boolean} enabled @returns {Promise<MyLocation>} */
export const setLocationBackground = (enabled) => apiFetch("/location/background", { method: "PUT", body: { enabled } });

/**
 * 하루 이동 기록. 본인 것, 부모(관리자)는 userId 로 가족 구성원 것도 볼 수 있다. 좌표는 없다.
 * @typedef {{ kind: "stay" | "move" | "no_record" | "anomaly", start: string, end: string, place: string | null, origin: string | null, candidate_id: string | null }} Segment
 * @typedef {{ date: string, user_id: string, name: string, sharing: boolean, can_name: boolean, segments: Segment[] }} Timeline
 * @typedef {{ places: { id: string, name: string }[], candidates: { id: string, label: string, visits: number, last_seen: string }[] }} Places
 * @param {string} date YYYY-MM-DD
 * @param {string | null} [userId]
 * @returns {Promise<Timeline>}
 */
export const getTimeline = (date, userId) =>
  apiFetch(`/location/timeline?date=${encodeURIComponent(date)}${userId ? `&user_id=${encodeURIComponent(userId)}` : ""}`);

/** 내가 이름 붙인 장소와 이름 붙이기를 제안하는 자주 간 곳. @returns {Promise<Places>} */
export const getPlaces = () => apiFetch("/location/places");

/** 자주 간 곳에 이름을 붙인다(본인만, 20자, 최대 20곳). @param {string} candidateId @param {string} name @returns {Promise<Places>} */
export const namePlace = (candidateId, name) =>
  apiFetch("/location/places", { method: "POST", body: { candidate_id: candidateId, name } });

/** 내가 붙인 장소 이름을 지운다. @param {string} placeId @returns {Promise<Places>} */
export const deletePlace = (placeId) => apiFetch(`/location/places/${encodeURIComponent(placeId)}`, { method: "DELETE" });
