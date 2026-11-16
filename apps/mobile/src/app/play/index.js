import TabBell from "@/features/notifications/components/TabBell";
import PlayMainScreen from "@/features/playground/screens/PlayMainScreen";

/** 놀이터 메인 라우트: 순위 아이콘 오른쪽에 알림 종을 여기서 조립한다(기능끼리 서로 import 하지 않게). */
export default function PlayRoute() {
  return <PlayMainScreen bell={<TabBell />} />;
}
