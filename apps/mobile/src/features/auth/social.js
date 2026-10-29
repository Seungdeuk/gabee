/**
 * Google·Kakao 로그인 설정과 순수 도우미. 앱 키(클라이언트 ID)는 공개 값이라 EXPO_PUBLIC_* 로 두지만,
 * 앱 시크릿 같은 비밀값은 앱에 넣지 않는다(서버 .env 에만 둔다). 값이 비어 있으면 그 로그인 버튼은 보이지 않는다.
 */

/** 제공자별 앱 설정. 비어 있으면 "". */
export const socialConfig = () => ({
  google: {
    web: process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID ?? "",
    ios: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID ?? "",
    android: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID ?? "",
  },
  kakao: { restApiKey: process.env.EXPO_PUBLIC_KAKAO_REST_API_KEY ?? "" },
});

/**
 * 이 앱에서 쓸 수 있게 설정된 제공자 목록.
 * @returns {("google" | "kakao")[]}
 */
export function enabledProviders() {
  // 출시 전 임시로 끔: EXPO_PUBLIC_SOCIAL_LOGIN_DISABLED=true 면 키가 있어도 버튼을 숨긴다(EAS preview·production 환경에 설정)
  if (process.env.EXPO_PUBLIC_SOCIAL_LOGIN_DISABLED === "true") return [];
  const cfg = socialConfig();
  const list = [];
  if (cfg.google.web || cfg.google.ios || cfg.google.android) list.push("google");
  if (cfg.kakao.restApiKey) list.push("kakao");
  return list;
}

export const PROVIDER_LABEL = { google: "Google", kakao: "카카오" };

/**
 * 소셜 로그인 응답이 "같은 이메일의 기존 계정이 있다"는 안내인지.
 * @param {object | null | undefined} res
 * @returns {boolean}
 */
export const isCandidate = (res) => Boolean(res && res.candidate_account === true && !res.access_token);
