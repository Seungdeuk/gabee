import { useRouter } from "expo-router";

import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";

/**
 * 가족 그룹 화면들의 공통 틀: 제목, 뒤로 가기, 스크롤 본문.
 * @param {{ title: string, subtitle?: string, children: import("react").ReactNode }} props
 */
export default function FamilyFrame({ title, subtitle, children }) {
  const router = useRouter();
  return (
    <Screen
      title={title}
      subtitle={subtitle}
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/more"))} />}
    >
      {children}
    </Screen>
  );
}
