import { apiFetch } from "@/shared/api/client";

/**
 * 현재 가족의 **비공개** 추억 후보(읽기 전용). 서버가 조회할 때마다 자격을 다시 확인해 주므로 지운·철회·제외된 사진은 응답에 없다.
 * 오류: 404(미출시 가드가 꺼져 있음 — 빈 목록이 아니다), 401(로그인 만료), 403(이 가족 구성원이 아님), 503(기능 준비 중).
 * @returns {Promise<{ items: { id: string, status: "private", representative: object, photos: { attachment_id: string, thumb_url: string, photo_url: string, taken_at: string | null, is_representative: boolean }[], photo_count: number, dated_count: number, undated_count: number, starts_at: string | null, ends_at: string | null, bridged: boolean, score: number, algorithm_version: string, updated_at: string }[] }>}
 */
export const listMemoryCandidates = () => apiFetch("/family-memory/candidates");