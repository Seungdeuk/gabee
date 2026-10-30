import { CONSENT_VERSION } from "./consentCopy.js";

/** 로그인한 사용자가 현재 버전의 동의서에 동의하지 않았으면 동의 화면을 보여야 한다. 동의하지 않으면 앱을 쓸 수 없다. */
export function needsTesterConsent(user) {
  if (!user?.id) return false;
  return user.tester_consent_version !== CONSENT_VERSION;
}
