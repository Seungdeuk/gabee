import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors, spacing } from "@/theme";

/**
 * 입력창 위 빠른 질문 칩 한 줄(가로 스크롤). 누르면 그 문장이 바로 전송된다.
 * @param {{ questions: string[], onPress: (question: string) => void }} props
 */
export default function QuickChips({ questions, onPress }) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.scroll}
      contentContainerStyle={styles.row}
      keyboardShouldPersistTaps="handled"
    >
      {questions.map((question) => (
        <Pressable key={question} onPress={() => onPress(question)} style={styles.chip} accessibilityRole="button">
          <Text style={styles.text}>{question}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  // 가로 스크롤은 세로로 늘어나지 않게 칩 높이만큼만 쓴다.
  scroll: { flexGrow: 0, flexShrink: 0 },
  row: { gap: 6, paddingVertical: 2 },
  chip: {
    paddingVertical: 6,
    paddingHorizontal: 13,
    borderRadius: 999,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  text: { fontSize: 14, fontWeight: "500", color: colors.text, paddingHorizontal: spacing.xs - 4 },
});
