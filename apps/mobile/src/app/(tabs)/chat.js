import { useFocusEffect, useRouter } from "expo-router";
import { useCallback } from "react";

import AiAssistantScreen from "@/features/ai-assistant/screens/AiAssistantScreen";
import { checkSettlementReminders } from "@/features/billing/api";
import { badgeLabel } from "@/features/notifications/format";
import useUnread from "@/features/notifications/useUnread";

/** 홈(AI 채팅) 라우트: 상단 종 아이콘(알림함)을 여기서 연결한다. 기능끼리 서로를 import 하지 않게 라우트에서 조립한다. */
export default function ChatRoute() {
  const router = useRouter();
  const { total, refresh } = useUnread();
  // 홈에 올 때마다 내 정산 재알림을 확인하고, 만들어졌을 수 있으니 안 읽은 개수를 한 번 더 읽는다(알림 기능 파일은 건드리지 않는다).
  // 확인이 실패해도 홈은 그대로다(서버가 안 돼도 조용히 넘어간다).
  useFocusEffect(
    useCallback(() => {
      checkSettlementReminders()
        .then(refresh)
        .catch(() => {});
    }, [refresh]),
  );
  return <AiAssistantScreen onBell={() => router.push("/notifications")} bellBadge={badgeLabel(total)} />;
}
