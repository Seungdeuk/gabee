import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";

import { colors } from "@/theme";

/** 게임 아이콘(games.js 의 icon) 하나를 그린다. */
export default function PlayIcon({ icon, size = 22, color = colors.text }) {
  const IconSet = icon.set === "mci" ? MaterialCommunityIcons : Ionicons;
  return <IconSet name={icon.name} size={size} color={color} />;
}
