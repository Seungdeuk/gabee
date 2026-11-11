import { useRouter } from "expo-router";
import { useEffect } from "react";

/**
 * Google 로그인이 끝나고 앱으로 돌아오는 주소(<패키지 이름>:/oauthredirect)를 받는 빈 라우트.
 * 안드로이드에서는 앱 라우터도 이 주소를 받아 "없는 화면"(Unmatched Route)이 되기 때문에 두었다(`kakao.js` 와 같은 이유).
 * 로그인 결과는 SocialButtons 의 인증 세션이 이어받으니 여기서는 이전 화면(로그인)으로 돌려보내기만 한다.
 * @returns {null}
 */
export default function OAuthRedirectRoute() {
  const router = useRouter();
  useEffect(() => {
    if (router.canGoBack()) router.back();
    else router.replace("/login");
  }, [router]);
  return null;
}
