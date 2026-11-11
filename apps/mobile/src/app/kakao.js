import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import { kakaoReturnBus } from "@/features/auth/kakaoReturn";

/**
 * 카카오 로그인이 끝나고 앱으로 돌아오는 주소(gabee://kakao)를 받는 빈 라우트.
 * 안드로이드에서는 앱 라우터도 이 주소를 받아 "없는 화면"이 되기 때문에 두었다. 보통은 로그인 결과를 SocialButtons 가
 * 인증 창에서 바로 이어받지만, 카카오톡 앱으로 로그인하면 인증 창은 "닫힘"으로 끝나고 코드는 이 주소로만 들어온다.
 * 그래서 받은 값(code·state)을 알림 통으로 알려 진행 중인 로그인이 이어받게 한 뒤 이전 화면으로 돌려보낸다.
 * @returns {null}
 */
export default function KakaoReturnRoute() {
  const router = useRouter();
  const params = useLocalSearchParams();
  useEffect(() => {
    kakaoReturnBus.publish(params);
    if (router.canGoBack()) router.back();
    else router.replace("/login");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- 들어올 때 한 번만 알리고 돌아간다
  return null;
}
