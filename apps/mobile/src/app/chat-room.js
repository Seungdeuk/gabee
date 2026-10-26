import { useLocalSearchParams } from "expo-router";

import ChatRoomScreen from "@/features/family-chat/screens/ChatRoomScreen";

/** 방마다 화면을 새로 만든다(같은 화면이 다른 방으로 재사용되어 이전 방 상태가 남는 일을 막는다). */
export default function ChatRoomRoute() {
  const { roomId } = useLocalSearchParams();
  return <ChatRoomScreen key={typeof roomId === "string" && roomId ? roomId : "family"} />;
}
