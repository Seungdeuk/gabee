import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { colors } from "@/theme";

const prompts = ["이번 주\n공과금 알려줘", "아빠 약\n챙겼는지 물어봐 줘", "영수증으로\n지출 보고서"];

/**
 * 빈 화면에서 보여 주는 추천 질문. 누르면 그 질문을 바로 보낸다.
 * @param {{ onPick: (text: string) => void }} props
 */
export default function PromptChips({ onPick }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
      {prompts.map((text) => (
        <Pressable
          key={text}
          onPress={() => onPick(text.replace("\n", " "))}
          style={({ pressed }) => [styles.chip, pressed && styles.pressed]}
          accessibilityRole="button"
        >
          <Text style={styles.text}>{text}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 16, gap: 8 },
  chip: {
    width: 124,
    minHeight: 60,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    backgroundColor: colors.card,
  },
  pressed: { backgroundColor: colors.surface },
  text: { fontSize: 13, lineHeight: 19, color: colors.text },
});
