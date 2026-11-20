import { apiFetch } from "@/shared/api/client";

// 동의·설정 API 호출(T31 기술 준비). 고지문이 확정되기 전에는 동의하는 호출을 화면이 만들지 않는다(consent.js 의 consentBody 가 null).

/** 서버 스위치·가족 설정·내 동의 상태. @returns {Promise<{ server_enabled: boolean, family_enabled: boolean, can_manage: boolean, me: { consented: boolean, retro_consented: boolean, consent_version: number | null } }>} */
export const getMemorySettings = () => apiFetch("/family-memory/settings");

/** 가족 기능 켜기/끄기(소유자·관리자만). 켜는 것은 서버가 열려 있을 때만(403 memory_disabled). */
export const setFamilyMemoryEnabled = (enabled) => apiFetch("/family-memory/settings", { method: "PUT", body: { enabled } });

/**
 * 내 동의/철회. 본문은 `consentBody()` 가 만든 것을 그대로 쓴다(동의에는 고지문 버전 포함). 오류: 409 consent_version_mismatch(고지문이 바뀜), 403 memory_disabled.
 * @param {{ consent: boolean, consent_version?: number }} body
 */
export const putMemoryConsent = (body) => apiFetch("/family-memory/consent", { method: "PUT", body });

/** 과거 사진 소급 분석 동의(기본 동의와 별개, 기록만 하고 분석 경로는 아직 없다). */
export const putMemoryRetroConsent = (consent) => apiFetch("/family-memory/consent/retro", { method: "PUT", body: { consent } });

/** 내가 올린 사진을 AI 분석에서 빼거나 다시 넣는다(타임라인 제외와 별개). */
export const putPhotoExclusion = (attachmentId, excluded) => apiFetch(`/family-memory/photos/${encodeURIComponent(attachmentId)}/exclusion`, { method: "PUT", body: { excluded } });