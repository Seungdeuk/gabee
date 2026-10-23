import { StyleSheet, Text } from "react-native";

import { colors, font, radius } from "@/theme";

const STYLES = {
  pending: { label: "기다려요", backgroundColor: colors.surfaceStrong, color: colors.text },
  accepted: { label: "수락", backgroundColor: colors.success, color: colors.onDark },
  cancelled: { label: "취소됨", backgroundColor: colors.border, color: colors.textMuted },
  declined: { label: "어려웠어요", backgroundColor: colors.border, color: colors.textMuted },
};

/**
 * 같이의 상태 배지. 어려웠어요·취소됨은 오류 색이 아니라 중립색이다(마음 상하지 않게).
 * @param {{ status: "pending" | "accepted" | "cancelled" | "declined" }} props
 */
export default function StatusBadge({ status }) {
  const { label, backgroundColor, color } = STYLES[status];
  return <Text style={[styles.badge, { backgroundColor, color }]}>{label}</Text>;
}

const styles = StyleSheet.create({
  badge: {
    ...font.caption,
    alignSelf: "flex-start",
    fontWeight: "500",
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
});
