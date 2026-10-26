import { useLocalSearchParams } from "expo-router";

import ChatRoomScreen from "@/features/family-chat/screens/ChatRoomScreen";

/** 방마다, 그리고 검색 결과로 여는 위치(focus)마다 화면을 새로 만든다(같은 화면이 다른 방·위치로 재사용되어 이전 상태가 남는 일을 막는다). */
export default function ChatRoomRoute() {
  const { roomId, focus } = useLocalSearchParams();
  const room = typeof roomId === "string" && roomId ? roomId : "family";
  const at = typeof focus === "string" && focus ? focus : "";
  return <ChatRoomScreen key={`${room}:${at}`} />;
}
