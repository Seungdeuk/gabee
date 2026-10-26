import * as Google from "expo-auth-session/providers/google";
import { exchangeCodeAsync, makeRedirectUri, useAuthRequest } from "expo-auth-session";
import * as WebBrowser from "expo-web-browser";
import { useEffect } from "react";

import Button from "@/shared/components/Button";

import { enabledProviders, socialConfig } from "../social";

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
  return <Button label="Google로 계속하기" variant="secondary" onPress={() => promptAsync()} disabled={disabled || !request} testID="social-google" />;
}

/** 카카오: 시스템 브라우저 OAuth(PKCE)로 받은 코드를 액세스 토큰으로 바꿔 서버에 넘긴다. */
function KakaoButton({ onToken, disabled }) {
  const clientId = socialConfig().kakao.restApiKey;
  const redirectUri = makeRedirectUri({ scheme: "gabee", path: "kakao" });
  const [request, response, promptAsync] = useAuthRequest({ clientId, redirectUri, usePKCE: true, scopes: ["account_email", "profile_nickname"] }, KAKAO);
  useEffect(() => {
    if (response?.type !== "success") {
      if (response?.type === "error") onToken("kakao", null);
      return;
    }
    exchangeCodeAsync({ clientId, code: response.params.code, redirectUri, extraParams: { code_verifier: request.codeVerifier } }, KAKAO)
      .then((tokens) => onToken("kakao", tokens.accessToken))
      .catch(() => onToken("kakao", null));
  }, [response]); // eslint-disable-line react-hooks/exhaustive-deps
  return <Button label="카카오로 계속하기" variant="secondary" onPress={() => promptAsync()} disabled={disabled || !request} testID="social-kakao" />;
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
