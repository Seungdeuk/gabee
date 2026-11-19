// AI 추억 동의 화면의 **기술적 준비**(T31): 서버 상태에서 화면이 무엇을 보여 줄지 정하는 순수 로직. **개인정보 고지문이 확정되지 않았으므로 동의 수집은 꺼져 있다**
// (`MEMORY_NOTICE_FINAL = false`). 고지문 문구·보관/삭제 정책은 이 파일이 정하지 않고 별도 승인 뒤에 확정한다. 철회·기능 끄기는 고지문·서버 스위치와 상관없이 언제나 가능하다.
// 주의: `consent_version` 값만으로 사용자가 고지문을 실제로 봤다는 것을 증명하지 못한다. 고지문을 실제로 보여 주고 사용자가 명시적으로 동의한 뒤에만 보내야 한다.

/** 고지문 확정 여부. 확정 전에는 동의·소급 동의·가족 활성화를 받는 컨트롤을 만들지 않는다. 확정 승인 뒤에 true 로 바꾼다. */
export const MEMORY_NOTICE_FINAL = false;

/** 서버(`family_memory.service.CONSENT_VERSION`)가 받는 동의 고지문 버전. 서버와 같아야 하고, 다르면 서버가 409 로 거절한다. */
export const REQUIRED_CONSENT_VERSION = 1;

/**
 * 서버 `GET /family-memory/settings` 응답에서 화면 상태를 정한다.
 * @param {{ server_enabled: boolean, family_enabled: boolean, can_manage: boolean, me: { consented: boolean, retro_consented: boolean, consent_version: number | null } }} settings
 * @param {{ noticeFinal?: boolean, requiredVersion?: number }} [options]
 * @returns {{
 *   collecting: boolean, blockedReason: "notice_not_final" | "server_off" | null,
 *   family: { enabled: boolean, canEnable: boolean, canDisable: boolean },
 *   me: { consented: boolean, needsReconsent: boolean, canConsent: boolean, canWithdraw: boolean },
 *   retro: { consented: boolean, canEnable: boolean, canDisable: boolean },
 * }}
 */
export function consentUiState(settings, { noticeFinal = MEMORY_NOTICE_FINAL, requiredVersion = REQUIRED_CONSENT_VERSION } = {}) {
  const serverOn = settings?.server_enabled === true;
  const me = settings?.me ?? {};
  const consented = me.consented === true;
  const versionOk = consented && me.consent_version === requiredVersion;
  const blockedReason = !noticeFinal ? "notice_not_final" : !serverOn ? "server_off" : null;
  const collecting = blockedReason === null;
  return {
    collecting,
    blockedReason,
    // 가족 활성화는 소유자·관리자만, 켜는 것은 고지문이 확정되고 서버가 열려 있을 때만. 끄는 것은 언제나(서버가 항상 허용한다)
    family: { enabled: settings?.family_enabled === true, canEnable: collecting && settings?.can_manage === true, canDisable: settings?.can_manage === true && settings?.family_enabled === true },
    // 업로더별 동의: 고지문 확정 뒤에만 받고, 버전이 바뀌었으면 다시 동의가 필요하다. 철회는 언제나
    me: { consented, needsReconsent: consented && !versionOk, canConsent: collecting && (!consented || !versionOk), canWithdraw: consented },
    // 소급 분석은 기본 동의와 별개의 명시적 동의이고 기본 동의가 유효할 때만 켤 수 있다. 끄는 것은 언제나
    retro: { consented: me.retro_consented === true, canEnable: collecting && versionOk && me.retro_consented !== true, canDisable: me.retro_consented === true },
  };
}

/**
 * 동의 요청 본문. 동의(true)에는 사용자가 본 고지문 버전을 함께 보내고, 철회(false)에는 버전을 보내지 않는다.
 * 고지문이 확정되기 전에는 동의 본문을 만들지 않는다(null).
 * @param {boolean} consent
 * @param {{ noticeFinal?: boolean, version?: number }} [options]
 * @returns {{ consent: boolean, consent_version?: number } | null}
 */
export function consentBody(consent, { noticeFinal = MEMORY_NOTICE_FINAL, version = REQUIRED_CONSENT_VERSION } = {}) {
  if (!consent) return { consent: false };
  return noticeFinal ? { consent: true, consent_version: version } : null;
}