import { useLocalSearchParams } from "expo-router";

import ChatBoardScreen from "@/features/family-chat/screens/ChatBoardScreen";

/** 방마다 화면을 새로 만든다(다른 방의 게시판이 잠깐 보이지 않게). */
export default function ChatBoardRoute() {
  const { roomId } = useLocalSearchParams();
  return <ChatBoardScreen key={typeof roomId === "string" && roomId ? roomId : "family"} />;
}
