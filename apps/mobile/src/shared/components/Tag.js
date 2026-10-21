import { StyleSheet, Text } from "react-native";

import { colors } from "@/theme";

const tones = {
  gray: { backgroundColor: colors.surfaceStrong, color: colors.textSub },
  blue: { backgroundColor: colors.primarySoft, color: colors.primaryDark },
  green: { backgroundColor: colors.successSoft, color: "#137A41" },
  orange: { backgroundColor: colors.warningSoft, color: "#A35400" },
  red: { backgroundColor: colors.dangerSoft, color: "#C62436" },
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
    fontWeight: "600",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    overflow: "hidden",
  },
});
