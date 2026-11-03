import * as Google from "expo-auth-session/providers/google";
import { exchangeCodeAsync, makeRedirectUri, useAuthRequest } from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";
import { useEffect, useRef } from "react";
import { Platform } from "react-native";

import { apiUrl } from "@/shared/api/client";
import Button from "@/shared/components/Button";

import { enabledProviders, KAKAO_APP_RETURN_URL, KAKAO_RELAY_PATH, kakaoRedirectUri, socialConfig } from "../social";

// 시스템 브라우저에서 돌아온 로그인 결과를 앱이 이어받는다(웹에서 꼭 필요하다).
WebBrowser.maybeCompleteAuthSession();

const KAKAO = {
  authorizationEndpoint: "https://kauth.kakao.com/oauth/authorize",
  tokenEndpoint: "https://kauth.kakao.com/oauth/token",
};

/** Google: 시스템 브라우저 OAuth(PKCE)로 ID 토큰을 받아 서버에 넘긴다. */
function GoogleButton({ onToken, disabled }) {
  const cfg = socialConfig().google;
  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    webClientId: cfg.web || undefined,
    iosClientId: cfg.ios || undefined,
    androidClientId: cfg.android || undefined,
  });
  useEffect(() => {
    if (response?.type === "success") onToken("google", response.params.id_token);
    else if (response?.type === "error") onToken("google", null);
  }, [response]); // eslint-disable-line react-hooks/exhaustive-deps
  return <Button label="Google로 계속하기" icon="logo-google" variant="secondary" onPress={() => promptAsync()} disabled={disabled || !request} testID="social-google" />;
}

/**
 * 카카오: 시스템 브라우저 OAuth(PKCE)로 받은 코드를 액세스 토큰으로 바꿔 서버에 넘긴다.
 * 카카오는 앱 주소(gabee://)를 Redirect URI 로 받지 않아서 모바일은 서버 https 중계 주소로 코드를 돌려받고,
 * 서버가 그 코드를 앱 주소로 넘겨 주면 앱이 이어받는다. 웹은 웹 주소로 바로 돌아온다.
 */
function KakaoButton({ onToken, disabled }) {
  const clientId = socialConfig().kakao.restApiKey;
  const appReturnUrl = Platform.OS === "web" ? makeRedirectUri({ scheme: "gabee", path: "kakao" }) : KAKAO_APP_RETURN_URL; // 모바일은 서버가 넘겨 주는 주소로 고정(Expo Go 는 주소가 달라 시험할 수 없다)
  const busy = useRef(false); // 인증 창이 열려 있는 동안 다시 누르지 못하게(promptAsync 와 달리 직접 여는 쪽에는 잠금이 없다)
  const redirectUri = kakaoRedirectUri({ platform: Platform.OS, appReturnUrl, relayUrl: apiUrl(KAKAO_RELAY_PATH) });
  const [request, response, promptAsync] = useAuthRequest({ clientId, redirectUri, usePKCE: true, scopes: ["account_email", "profile_nickname"] }, KAKAO);
  /** 시스템 브라우저에서 돌아온 결과(성공이면 코드)를 액세스 토큰으로 바꿔 넘긴다. 취소는 그냥 둔다. */
  const finish = (res) => {
    if (res?.type !== "success") {
      if (res?.type === "error") onToken("kakao", null);
      return;
    }
    exchangeCodeAsync({ clientId, code: res.params.code, redirectUri, extraParams: { code_verifier: request.codeVerifier } }, KAKAO)
      .then((tokens) => onToken("kakao", tokens.accessToken))
      .catch(() => onToken("kakao", null));
  };
  useEffect(() => {
    finish(response);
  }, [response]); // eslint-disable-line react-hooks/exhaustive-deps
  const press = async () => {
    if (Platform.OS === "web") {
      promptAsync();
      return;
    }
    // 모바일: 인증 창은 https 중계 주소(redirectUri)로 돌아오지만, 앱은 서버가 넘겨 주는 앱 주소로 돌아오기를 기다린다
    if (busy.current) return;
    busy.current = true;
    try {
      const result = await WebBrowser.openAuthSessionAsync(request.url, appReturnUrl);
      if (result.type === "success") finish(request.parseReturnUrl(result.url));
    } catch {
      onToken("kakao", null); // 인증 창을 열지 못한 경우
    } finally {
      busy.current = false;
    }
  };
  return <Button label="카카오로 계속하기" icon="chatbubble" variant="secondary" onPress={press} disabled={disabled || !request} testID="social-kakao" />;
}

/**
 * 소셜 로그인 버튼 묶음(앱에 설정된 제공자만, only 로 더 좁힐 수 있다). 시스템 브라우저에서 토큰을 받으면 onToken(provider, token) 을 부른다.
 * 로그인할지 계정에 연결할지는 부르는 쪽이 정한다. 중간에 실패하면 onFail(provider) 를 부른다.
 * @param {{ onToken: (provider: "google" | "kakao", token: string) => void, onFail?: (provider: "google" | "kakao") => void, disabled?: boolean, only?: ("google" | "kakao")[] }} props
 */
export default function SocialButtons({ onToken, onFail, disabled = false, only }) {
  const providers = enabledProviders().filter((p) => !only || only.includes(p));
  const handle = (provider, token) => (token ? onToken(provider, token) : onFail?.(provider));
  return (
    <>
      {providers.includes("google") ? <GoogleButton onToken={handle} disabled={disabled} /> : null}
      {providers.includes("kakao") ? <KakaoButton onToken={handle} disabled={disabled} /> : null}
    </>
  );
}
