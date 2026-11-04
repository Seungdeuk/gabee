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

/** 모바일에서 서버 중계가 인증 코드를 넘겨 주는 앱 주소(app.json scheme + 경로). 서버 `KAKAO_APP_RETURN` 과 같아야 한다. */
export const KAKAO_APP_RETURN_URL = "gabee://kakao";

/** 서버의 카카오 로그인 중계 경로(`/auth/kakao/callback`). 카카오 콘솔의 Redirect URI 에 https 주소로 등록한다. */
export const KAKAO_RELAY_PATH = "/auth/kakao/callback";

/**
 * 카카오 로그인이 인증 코드를 돌려받을 주소(Redirect URI).
 * 카카오는 사용자 지정 앱 주소(gabee://)를 Redirect URI 로 받지 않는다. 그래서 웹은 앱 주소(웹 주소)를 그대로 쓰고,
 * 모바일은 서버의 https 중계 주소로 돌려받은 뒤 서버가 코드를 앱 주소로 넘겨 준다(앱은 앱 주소로 돌아오기를 기다린다).
 * @param {{ platform: string, appReturnUrl: string, relayUrl: string }} args platform: "web" | "ios" | "android"
 * @returns {string}
 */
export const kakaoRedirectUri = ({ platform, appReturnUrl, relayUrl }) => (platform === "web" ? appReturnUrl : relayUrl);

export const PROVIDER_LABEL = { google: "Google", kakao: "카카오" };

/**
 * 소셜 로그인 응답이 "같은 이메일의 기존 계정이 있다"는 안내인지.
 * @param {object | null | undefined} res
 * @returns {boolean}
 */
export const isCandidate = (res) => Boolean(res && res.candidate_account === true && !res.access_token);
