import FamilyGroupCard from "@/features/family-group/components/FamilyGroupCard";
import AccountCard from "@/shared/auth/AccountCard";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";

import AppManageCard from "../components/AppManageCard";

/** 마이 페이지(하단 탭): 내 계정, 가족 그룹, 앱 관리. 각 화면 위 설정 버튼(/more)도 이 탭으로 온다. */
export default function MoreScreen() {
  return (
    <Screen title="마이 페이지" subtitle="내 정보와 앱 관리">
      <SectionTitle title="계정" />
      <AccountCard />

      <SectionTitle title="가족 그룹" />
      <FamilyGroupCard />

      <SectionTitle title="앱 관리" />
      <AppManageCard />
    </Screen>
  );
}
