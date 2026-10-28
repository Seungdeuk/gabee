import { useRouter } from "expo-router";

import AiAssistantScreen from "@/features/ai-assistant/screens/AiAssistantScreen";
import { badgeLabel } from "@/features/notifications/format";
import useUnread from "@/features/notifications/useUnread";

/** 홈(AI 채팅) 라우트: 상단 종 아이콘(알림함)을 여기서 연결한다. 기능끼리 서로를 import 하지 않게 라우트에서 조립한다. */
export default function ChatRoute() {
  const router = useRouter();
  const { total } = useUnread();
  return <AiAssistantScreen onBell={() => router.push("/notifications")} bellBadge={badgeLabel(total)} />;
}
