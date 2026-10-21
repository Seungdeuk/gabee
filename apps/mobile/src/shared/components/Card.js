import { StyleSheet, View } from "react-native";

import { colors, radius } from "@/theme";

const tones = {
  default: { backgroundColor: colors.surface },
  white: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.divider },
  blue: { backgroundColor: colors.surface }, // 강조 카드(옅은 꿀색)
  orange: { backgroundColor: colors.peachSoft },
  red: { backgroundColor: colors.peachSoft },
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
    borderRadius: radius.card,
    paddingVertical: 16,
    paddingHorizontal: 18,
    gap: 10,
  },
});
