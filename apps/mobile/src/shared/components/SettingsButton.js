import { useRouter } from "expo-router";

import IconButton from "./IconButton";

/**
 * 모든 탭 화면 상단 오른쪽 맨 끝의 설정 버튼(세로 점 세 개). 누르면 설정 화면(/more: 계정·가족 그룹·설정)으로 간다.
 * @returns {import("react").ReactElement}
 */
export default function SettingsButton() {
  const router = useRouter();
  return <IconButton name="ellipsis-vertical" size={20} label="설정" onPress={() => router.push("/more")} />;
}
