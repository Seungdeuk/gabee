import { apiFetch } from "@/shared/api/client";

/**
 * 돌봄 서버 호출. 응답 모양은 docs/contracts/openapi.json 의 /care/* 를 따른다.
 * @typedef {{ done: boolean | null, number: number | null, condition: "good" | "normal" | "bad" | null, recorded_by: string, recorded_at: string, skipped: boolean, late: boolean }} Entry
 * @typedef {{ id: string, name: string, mode: "yesno" | "number" | "condition", unit: string, target: number | null, scheduled_time: string, meal_type: string | null, entry: Entry | null, completed: boolean, missing: boolean, skipped: boolean, status: "done" | "skipped" | "missing" | "due" | "upcoming", minutes_until: number | null }} CareItem
 * @typedef {{ meal: "breakfast" | "lunch" | "dinner", label: string, item_id: string, scheduled_time: string, status: CareItem["status"], answer: "yes" | "no" | null }} MealStatus
 * @typedef {{ date: string, now: string, items: CareItem[], missing_ids: string[], meals: MealStatus[], upcoming_ids: string[], cleanup_ids: string[], skipped_ids: string[], done_ids: string[] }} Daily
 * @typedef {{ rule: string, item_id: string | null, text: string }} Recommendation
 * @typedef {{ date: string, meal: "breakfast" | "lunch" | "dinner", label: string, menu: string, note: string, source: "typed" | "recommended", recorded_by_name: string, recorded_at: string }} MealLogEntry
 * @typedef {{ meal: string, label: string, item_id: string | null, menu: string, index: number, next_index: number, total: number }} Meal
 */

// 개발용: 시각에 따라 달라지는 화면(다가오는 일정·누락)을 확인할 때 '지금' 시각을 바꾼다(EXPO_PUBLIC_DEV_NOW=HH:MM). 비우면 실제 시각.
const DEV_NOW = process.env.EXPO_PUBLIC_DEV_NOW ?? "";

/**
 * 데일리 체크 항목과 오늘 기록. 상태(done/skipped/missing/due/upcoming), 끼니 요약, 다가오는 일정·지난 항목 순서는 서버가 계산한다.
 * @returns {Promise<Daily>}
 */
export const getDaily = () => apiFetch(`/care/daily${DEV_NOW ? `?at=${DEV_NOW}` : ""}`);

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
 * @param {{ done?: boolean, number?: number, condition?: "good" | "normal" | "bad", skipped?: boolean }} value skipped: 값 없이 '건너뛰기'
 * @returns {Promise<Entry>}
 */
export const putEntry = (id, value) => apiFetch(`/care/items/${id}/entry`, { method: "PUT", body: value });

/** 오늘의 기록·건너뛰기를 지워 되돌린다. @param {string} id */
export const deleteEntry = (id) => apiFetch(`/care/items/${id}/entry`, { method: "DELETE" });

/** 규칙 기반 추천. @returns {Promise<{ date: string, recommendations: Recommendation[] }>} */
export const getRecommendations = () => apiFetch("/care/recommendations");

/** 기록되지 않은 끼니의 첫 메뉴. @returns {Promise<{ date: string, meals: Meal[] }>} */
export const getMeals = () => apiFetch("/care/meals");

/** '다른 메뉴': 직전 응답의 next_index 를 넘기면 다음 메뉴가 나온다. @returns {Promise<Meal>} */
export const getMealMenu = (meal, index) => apiFetch(`/care/meals/${meal}?index=${index}`);

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

/** 가족 구성원의 최신 위치. 동의하지 않은 사람은 좌표 없이 sharing=false 로 온다. @returns {Promise<{ members: MemberLocation[], retention_days: number }>} */
export const getLatestLocations = () => apiFetch("/care/locations/latest");

/**
 * 식단 기록: 최근 days 일(1~31). 날짜마다 아침·점심·저녁 칸이 있고 기록이 없으면 log 가 null 이다.
 * @param {number} [days]
 * @returns {Promise<{ start: string, end: string, days: { date: string, slots: { meal: MealLogEntry["meal"], label: string, log: MealLogEntry | null }[] }[] }>}
 */
export const getMealLog = (days = 7) => apiFetch(`/care/meal-log?days=${days}`);

/**
 * 그날 끼니에 먹은 메뉴를 기록한다(같은 끼니는 덮어씀). 그 끼니의 데일리 체크도 완료가 된다.
 * @param {{ meal: MealLogEntry["meal"], menu: string, note?: string, source?: "typed" | "recommended", date?: string }} body
 * @returns {Promise<MealLogEntry>}
 */
export const putMealLog = (body) => apiFetch("/care/meal-log", { method: "PUT", body });

/** 식단 기록을 지운다(데일리 체크는 그대로). @param {string} date YYYY-MM-DD @param {string} meal */
export const deleteMealLog = (date, meal) => apiFetch(`/care/meal-log?date=${date}&meal=${meal}`, { method: "DELETE" });
