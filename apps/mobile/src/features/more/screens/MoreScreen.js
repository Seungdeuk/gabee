import { useRouter } from "expo-router";

import FamilyGroupCard from "@/features/family-group/components/FamilyGroupCard";
import AccountCard from "@/shared/auth/AccountCard";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";

/** 설정 화면: 계정과 가족 그룹. */
export default function MoreScreen() {
  const router = useRouter();

  return (
    <Screen
      title="설정"
      subtitle="계정과 가족 그룹"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => router.back()} />}
    >
      <SectionTitle title="계정" />
      <AccountCard />

      <SectionTitle title="가족 그룹" />
      <FamilyGroupCard />
    </Screen>
  );
}
