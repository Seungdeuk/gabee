import { StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

const tones = {
  error: { backgroundColor: colors.dangerSoft, color: colors.danger },
  info: { backgroundColor: colors.surface, color: colors.textSub },
  success: { backgroundColor: colors.successSoft, color: colors.success },
};

/**
 * 안내·오류·성공 문구 상자. 내용이 비어 있으면 아무것도 그리지 않는다.
 * @param {{ tone?: keyof typeof tones, text?: string }} props
 */
export default function Notice({ tone = "info", text }) {
  if (!text) return null;
  const { color, ...box } = tones[tone];
  return (
    <View style={[styles.box, box]} accessibilityRole={tone === "error" ? "alert" : undefined}>
      <Text style={[styles.text, { color }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { borderRadius: 14, paddingVertical: 12, paddingHorizontal: 14 },
  text: { ...font.body },
});
