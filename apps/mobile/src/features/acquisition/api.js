import { apiFetch } from "@/shared/api/client";

/**
 * 설치 경로(유입 경로)를 서버에 한 번 저장한다. 서버는 이미 저장된 사람이면 그대로 두고 204 를 돌려준다.
 * @param {{source: string, medium?: string, campaign?: string}} tags parseReferrer 결과
 * @returns {Promise<void>}
 */
export const sendInstallSource = (tags) =>
  apiFetch("/acquisition/install-source", { method: "POST", body: tags });
