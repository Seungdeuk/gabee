import { apiFetch } from "@/shared/api/client";

/**
 * 이 가족 그룹의 최근 대화를 AI 로 요약한다. 누를 때만 서버가 대화를 AI 로 보내고, 요약과 대화는 저장되지 않는다.
 * @param {{ limit?: number, afterId?: number }} [range] 최근 limit 개(기본 200), afterId 를 주면 그 뒤의 대화
 * @returns {Promise<{ summary: string, message_count: number, from_message_id: number, to_message_id: number, model: string, generated_at: string }>}
 */
export const summarizeChat = ({ limit = 200, afterId = 0 } = {}) =>
  apiFetch("/family-chat/summary", { method: "POST", body: { limit, after_id: afterId } });
