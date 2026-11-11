import { Image } from "expo-image";
import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import mascot from "../../../../../assets/images/gabee-mascot.png";

/**
 * 가비 한마디: 왼쪽 가비 이미지, 오른쪽 말풍선.
 * @param {{ text: string }} props
 * @returns {import("react").ReactElement}
 */
export default function GabeeBubble({ text }) {
  return (
    <View style={styles.row}>
      <Image source={mascot} style={styles.mascot} contentFit="cover" accessibilityLabel="가비" />
      <View style={styles.bubble}>
        <Text style={styles.name}>가비</Text>
        <Text style={styles.text}>{text}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  mascot: { width: 56, height: 56, borderRadius: radius.lg },
  bubble: {
    flex: 1,
    gap: spacing.xs,
    padding: spacing.lg,
    borderRadius: radius.bubble,
    borderTopLeftRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  name: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily },
  text: { ...font.body, color: colors.text },
});
