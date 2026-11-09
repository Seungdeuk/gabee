import FamilyChatScreen from "@/features/family-chat/screens/FamilyChatScreen";
import TabBell from "@/features/notifications/components/TabBell";
import PlayEntryCard from "@/features/playground/components/PlayEntryCard";

/** 소통 탭 라우트: 가족 연락처 아래에 가족 놀이터 입구를, 상단 오른쪽 끝에 알림 종을 여기서 조립한다(기능끼리 서로 import 하지 않게). */
export default function FamilyChatRoute() {
  return <FamilyChatScreen playEntry={<PlayEntryCard />} bell={<TabBell />} />;
}
