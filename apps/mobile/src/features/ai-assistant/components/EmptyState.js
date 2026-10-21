import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius } from "@/theme";

const suggestions = [
  "오늘 가족 일정 알려줘",
  "이번 달 공동 지출 요약해줘",
  "부모님께 보낼 안부 문구 추천해줘",
  "오늘 돌봄 체크 현황 알려줘",
];

/**
 * 대화가 시작되기 전 인사말과 추천 질문.
 * @param {{ onPick: (text: string) => void }} props
 */
export default function EmptyState({ onPick }) {
  return (
    <View style={styles.container}>
      <View style={styles.logo}>
        <Ionicons name="sparkles" size={28} color={colors.primary} />
      </View>
      <Text style={styles.title}>무엇을 도와드릴까요?</Text>
      <Text style={styles.sub}>가족의 일정, 지출, 돌봄 기록을 함께 살펴봐요</Text>

      <View style={styles.list}>
        {suggestions.map((text) => (
          <Pressable
            key={text}
            onPress={() => onPick(text)}
            style={({ pressed }) => [styles.chip, pressed && styles.chipPressed]}
          >
            <Text style={styles.chipText}>{text}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    gap: 8,
  },
  logo: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primarySoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
  },
  title: {
    ...font.h1,
    color: colors.text,
    textAlign: "center",
  },
  sub: {
    ...font.body,
    color: colors.textMuted,
    textAlign: "center",
  },
  list: {
    alignSelf: "stretch",
    gap: 8,
    marginTop: 24,
  },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: colors.background,
  },
  chipPressed: {
    backgroundColor: colors.surface,
  },
  chipText: {
    ...font.body,
    color: colors.text,
  },
});
