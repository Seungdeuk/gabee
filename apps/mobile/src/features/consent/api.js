import { apiFetch } from "@/shared/api/client";

/** 동의한 동의서 버전을 서버에 저장한다(서버가 시각을 함께 기록). 갱신된 사용자 정보를 돌려준다. */
export const saveTesterConsent = (version) =>
  apiFetch("/family-group/auth/me/tester-consent", { method: "PUT", body: { version } });
