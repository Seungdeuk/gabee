import AiAssistantScreen from "@/features/ai-assistant/screens/AiAssistantScreen";
import JoinFamilyPrompt from "@/features/family-group/components/JoinFamilyPrompt";
import TabBell from "@/features/notifications/components/TabBell";

/** 홈(AI 채팅) 라우트: 상단 오른쪽 끝 알림 종(알림함)과 인사말 아래 가족 참여 버튼을 여기서 연결한다. 기능끼리 서로를 import 하지 않게 라우트에서 조립한다. */
export default function ChatRoute() {
  return <AiAssistantScreen bell={<TabBell />} emptyAction={<JoinFamilyPrompt />} />;
}
