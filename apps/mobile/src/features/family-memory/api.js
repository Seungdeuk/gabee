import { apiFetch } from "@/shared/api/client";

/**
 * 현재 가족의 **비공개** 추억 후보(읽기 전용). 서버가 조회할 때마다 자격을 다시 확인해 주므로 지운·철회·제외된 사진은 응답에 없다.
 * 오류: 404(미출시 가드가 꺼져 있음 — 빈 목록이 아니다), 401(로그인 만료), 403(이 가족 구성원이 아님), 503(기능 준비 중).
 * @returns {Promise<{ items: { id: string, status: "private", representative: object, photos: { attachment_id: string, thumb_url: string, photo_url: string, taken_at: string | null, is_representative: boolean }[], photo_count: number, dated_count: number, undated_count: number, starts_at: string | null, ends_at: string | null, bridged: boolean, score: number, algorithm_version: string, updated_at: string }[] }>}
 */
export const listMemoryCandidates = () => apiFetch("/family-memory/candidates");
/**
 * 사용자 요청형 추억 생성의 진행 상태(읽기 전용). 개수만 담는다. 오류: 404(입구가 꺼져 있음), 403 generation_not_open.
 * @returns {Promise<{ state: "needs_consent" | "not_enough_photos" | "idle" | "processing" | "ready" | "failed", eligible: number, embedded: number, processing: number, failed: number, candidates: number, enqueued: number, capped: boolean }>}
 */
export const getMemoryGeneration = () => apiFetch("/family-memory/generation");

/**
 * "추억 만들기" 요청(멱등). 자격 있는 사진을 분석 대기에 올리고, 모두 준비되면 후보를 새로 계산한다. 처리 중에는 같은 요청을 다시 보내 진행을 확인한다.
 * 오류: 404·403 generation_not_open(꺼져 있음), 403 consent_required·family_off·memory_disabled.
 * @returns {Promise<{ state: string, eligible: number, embedded: number, processing: number, failed: number, candidates: number, enqueued: number, capped: boolean }>}
 */
export const requestMemoryGeneration = () => apiFetch("/family-memory/generation", { method: "POST" });
