import { StyleSheet, Text } from "react-native";

import { colors } from "@/theme";

const tones = {
  gray: { backgroundColor: colors.honeySoft, color: colors.textMuted },
  blue: { backgroundColor: colors.surfaceStrong, color: colors.text },
  green: { backgroundColor: colors.successSoft, color: colors.success },
  orange: { backgroundColor: colors.surfaceStrong, color: colors.text },
  red: { backgroundColor: colors.dangerSoft, color: colors.danger },
};

/**
 * 작은 상태 태그.
 * @param {{ label: string, tone?: keyof typeof tones }} props
 */
export default function Tag({ label, tone = "gray" }) {
  const { backgroundColor, color } = tones[tone];
  return <Text style={[styles.tag, { backgroundColor, color }]}>{label}</Text>;
}

const styles = StyleSheet.create({
  tag: {
    alignSelf: "flex-start",
    fontSize: 12,
    fontWeight: "700",
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: "hidden",
  },
});
