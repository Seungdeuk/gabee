import { CONSENT_VERSION } from "./consentCopy.js";

// 이번에 앱을 켜 둔 동안 "동의하지 않아요"를 누른 사용자. 저장하지 않아서 앱을 다시 켜면 다시 묻는다.
const declined = new Set();

export const declineForNow = (userId) => declined.add(userId);

/** 로그인한 사용자가 현재 버전의 동의서에 동의하지 않았고, 이번에 거부하지도 않았으면 동의 화면을 보여야 한다. */
export function needsTesterConsent(user) {
  if (!user?.id) return false;
  return user.tester_consent_version !== CONSENT_VERSION && !declined.has(user.id);
}
