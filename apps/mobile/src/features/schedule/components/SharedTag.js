import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

/**
 * 공동 일정 이름표(알약). 제목 글줄 안에 끼운 중첩 Text 의 배경은 안드로이드에서 모서리가 각지고 아래가 잘려서, 따로 View 로 그린다.
 * @param {{ label: string }} props
 */
export default function SharedTag({ label }) {
  return (
    <View style={styles.tag}>
      <Text style={styles.text}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tag: { alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.surfaceStrong },
  text: { ...font.caption, lineHeight: 18, fontWeight: "500", color: colors.text, includeFontPadding: false },
});
