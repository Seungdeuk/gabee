import { apiFetch } from "@/shared/api/client";

/**
 * 돌봄 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /care/* 를 따른다.
 * @typedef {{ done: boolean | null, number: number | null, condition: "good" | "normal" | "bad" | null, recorded_by: string, recorded_at: string }} Entry
 * @typedef {{ id: string, name: string, mode: "yesno" | "number" | "condition", unit: string, target: number | null, scheduled_time: string, meal_type: string | null, entry: Entry | null, completed: boolean, missing: boolean }} CareItem
 * @typedef {{ date: string, now: string, items: CareItem[], missing_ids: string[] }} Daily
 * @typedef {{ rule: string, item_id: string | null, text: string }} Recommendation
 * @typedef {{ meal: string, label: string, item_id: string | null, menu: string, index: number, next_index: number, total: number }} Meal
 */

/** 데일리 체크 항목과 오늘 기록, 누락(서버가 계산). @returns {Promise<Daily>} */
export const getDaily = () => apiFetch("/care/daily");

/**
 * 항목 추가.
 * @param {{ name: string, mode: CareItem["mode"], unit: string, target: number | null, scheduled_time: string, meal_type: string | null }} body
 * @returns {Promise<CareItem>}
 */
export const addItem = (body) => apiFetch("/care/items", { method: "POST", body });

/** 소프트 삭제. @param {string} id */
export const deleteItem = (id) => apiFetch(`/care/items/${id}`, { method: "DELETE" });

/**
 * 오늘 기록(같은 날 다시 보내면 덮어쓴다). 항목의 기록 방식에 맞는 값 하나만 보낸다.
 * @param {string} id
 * @param {{ done?: boolean, number?: number, condition?: "good" | "normal" | "bad" }} value
 * @returns {Promise<Entry>}
 */
export const putEntry = (id, value) => apiFetch(`/care/items/${id}/entry`, { method: "PUT", body: value });

/** 규칙 기반 추천. @returns {Promise<{ date: string, recommendations: Recommendation[] }>} */
export const getRecommendations = () => apiFetch("/care/recommendations");

/** 기록되지 않은 끼니의 첫 메뉴. @returns {Promise<{ date: string, meals: Meal[] }>} */
export const getMeals = () => apiFetch("/care/meals");

/** '다른 메뉴': 직전 응답의 next_index 를 넘기면 다음 메뉴가 나온다. @returns {Promise<Meal>} */
export const getMealMenu = (meal, index) => apiFetch(`/care/meals/${meal}?index=${index}`);

/** 예시 위치(실제 GPS 아님). @returns {Promise<{ is_example: boolean, place: string, lat: number, lng: number, notice: string }>} */
export const getLocation = () => apiFetch("/care/location");
