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
 * 이 앱에서 쓸 수 있게 설정된 제공자 목록. Google 은 지금 기기(플랫폼)용 클라이언트 ID 가 있을 때만 켠다
 * (다른 플랫폼 ID 만 있는데 버튼을 그리면 안드로이드·iOS 에서 앱이 시작하자마자 "ClientId must be defined" 오류가 난다).
 * @param {string} [platform] "web" | "ios" | "android" (기본 "web")
 * @returns {("google" | "kakao")[]}
 */
export function enabledProviders(platform = "web") {
  // 출시 전 임시로 끔: EXPO_PUBLIC_SOCIAL_LOGIN_DISABLED=true 면 키가 있어도 버튼을 숨긴다(EAS preview·production 환경에 설정)
  if (process.env.EXPO_PUBLIC_SOCIAL_LOGIN_DISABLED === "true") return [];
  const cfg = socialConfig();
  const list = [];
  const googleId = platform === "android" ? cfg.google.android : platform === "ios" ? cfg.google.ios : cfg.google.web;
  if (googleId) list.push("google");
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

/** 카카오톡 앱에서 돌아온 코드를 기다리는 시간(로그인을 시작한 뒤). 카카오톡 앱에서 비밀번호·인증을 거치는 시간을 넉넉히 둔다. */
export const KAKAO_RETURN_WAIT_MS = 180_000;

/**
 * 카카오톡 앱으로 로그인하고 돌아온 주소(gabee://kakao?code=…&state=…)의 값을 받아도 되는지 판정한다.
 * 이번 로그인 요청의 state 와 같고(위조 방지), 아직 기다리는 중이며, 이미 처리한 코드가 아닐 때만 받는다.
 * @param {{ params: Record<string, unknown> | null | undefined, expectedState: string | undefined, pendingUntil: number, now: number, handledCode: string | null }} args
 * @returns {{ code: string } | { error: true } | null} 받을 코드, 카카오가 돌려준 오류, 또는 받지 않음(null)
 */
export function acceptKakaoReturn({ params, expectedState, pendingUntil, now, handledCode }) {
  if (!expectedState || !params || params.state !== expectedState) return null;
  if (!(now < pendingUntil)) return null;
  if (typeof params.error === "string" && params.error) return { error: true };
  const code = params.code;
  if (typeof code !== "string" || !code || code === handledCode) return null;
  return { code };
}

export const PROVIDER_LABEL = { google: "Google", kakao: "카카오" };

/**
 * 소셜 로그인 응답이 "같은 이메일의 기존 계정이 있다"는 안내인지.
 * @param {object | null | undefined} res
 * @returns {boolean}
 */
export const isCandidate = (res) => Boolean(res && res.candidate_account === true && !res.access_token);
