import { useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";

import AiAssistantScreen from "@/features/ai-assistant/screens/AiAssistantScreen";
import { checkSettlementReminders } from "@/features/billing/api";
import JoinFamilyPrompt from "@/features/family-group/components/JoinFamilyPrompt";
import TabBell from "@/features/notifications/components/TabBell";

/** 홈(AI 채팅) 라우트: 상단 오른쪽 끝 알림 종(알림함)과 인사말 아래 가족 참여 버튼을 여기서 연결한다. 기능끼리 서로를 import 하지 않게 라우트에서 조립한다. */
export default function ChatRoute() {
  // 종(TabBell) 안에서 안 읽은 개수를 읽으므로(알림 기능 파일은 건드리지 않는다), 홈에 올 때마다 내 정산 재알림을 확인하고
  // 새 알림이 만들어졌으면 종의 key 를 바꿔 다시 그려 개수를 한 번 더 읽게 한다. 확인이 실패해도 홈은 그대로다.
  const [bellKey, setBellKey] = useState(0);
  useFocusEffect(
    useCallback(() => {
      checkSettlementReminders()
        .then((res) => {
          if (res?.created > 0) setBellKey((k) => k + 1);
        })
        .catch(() => {});
    }, []),
  );
  return <AiAssistantScreen bell={<TabBell key={bellKey} />} emptyAction={<JoinFamilyPrompt />} />;
}
