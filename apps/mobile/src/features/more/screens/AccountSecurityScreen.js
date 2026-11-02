import { useRouter } from "expo-router";

import AccountCard from "@/shared/auth/AccountCard";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";

/**
 * 계정 및 보안: 이메일 인증, 소셜 계정 연결, 로그인·로그아웃은 공통 AccountCard 가 맡는다.
 * @returns {import("react").ReactElement}
 */
export default function AccountSecurityScreen() {
  const router = useRouter();
  return (
    <Screen
      title="계정 및 보안"
      subtitle="로그인과 계정을 관리해요"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      <AccountCard />
    </Screen>
  );
}
