import CareScreen from "@/features/care/screens/CareScreen";
import TabBell from "@/features/notifications/components/TabBell";

/** 지갑 탭 라우트: 상단 오른쪽 끝에 알림 종을 여기서 조립한다(기능끼리 서로 import 하지 않게). */
export default function CareRoute() {
  return <CareScreen bell={<TabBell />} />;
}
