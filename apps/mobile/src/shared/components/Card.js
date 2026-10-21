import { StyleSheet, View } from "react-native";

import { colors, radius } from "@/theme";

const tones = {
  default: { backgroundColor: colors.surface },
  white: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  blue: { backgroundColor: "#F0F6FF" },
  orange: { backgroundColor: "#FFF7EC" },
  red: { backgroundColor: "#FFF2F3" },
};

/**
 * 둥근 카드 컨테이너.
 * @param {{ tone?: keyof typeof tones, style?: object, children: import("react").ReactNode }} props
 */
export default function Card({ tone = "default", style, children }) {
  return <View style={[styles.card, tones[tone], style]}>{children}</View>;
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    paddingVertical: 16,
    paddingHorizontal: 18,
    gap: 10,
  },
});
