import { StyleSheet, Text } from "react-native";

import { colors, fonts } from "@/theme";

/**
 * 가비 로고: "Ga"는 브라운, "Bee"는 꿀색. 글꼴(Fredoka)은 app/_layout.js 에서 불러온다.
 * @param {{ size?: number }} props
 */
export default function Logo({ size = 22 }) {
  return (
    <Text style={[styles.logo, { fontSize: size }]} accessibilityLabel="GaBee">
      <Text style={{ color: colors.text }}>Ga</Text>
      <Text style={{ color: colors.accent }}>Bee</Text>
    </Text>
  );
}

const styles = StyleSheet.create({
  logo: {
    fontFamily: fonts.logo,
    letterSpacing: 0,
  },
});
