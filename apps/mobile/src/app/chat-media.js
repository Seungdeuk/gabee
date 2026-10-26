import { useLocalSearchParams } from "expo-router";

import ChatMediaScreen from "@/features/family-chat/screens/ChatMediaScreen";

/** 방마다 화면을 새로 만든다(다른 방의 모음이 잠깐 보이지 않게). */
export default function ChatMediaRoute() {
  const { roomId } = useLocalSearchParams();
  return <ChatMediaScreen key={typeof roomId === "string" && roomId ? roomId : "family"} />;
}
