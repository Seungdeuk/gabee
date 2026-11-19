import { apiFetch } from "@/shared/api/client";

/**
 * 한 번의 사용 기록(그날 탭별 초, 실행 횟수)을 서버의 하루 합계에 더한다.
 * @param {{day: string, opens: number, tabs: Record<string, number>}} report
 * @returns {Promise<void>}
 */
export const sendUsage = (report) => apiFetch("/usage/report", { method: "POST", body: report });
