import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * "한 주의 기록": 통계·일정 목록·인사이트를 접어 두는 영역. 뉴스가 읽힌 주는 접어 두고(defaultOpen=false),
 * 뉴스가 없는 주는 기록 요약을 바로 보이게 펼쳐 둔다. 사용자가 누른 뒤에는 그 선택을 따른다(주를 바꾸면 key 로 새로 시작한다).
 * @param {{ summary: string, defaultOpen: boolean, children: import("react").ReactNode }} props
 * @returns {import("react").ReactElement}
 */
export default function RecordFold({ summary, defaultOpen, children }) {
  const [choice, setChoice] = useState(null);
  const open = choice ?? defaultOpen;
  return (
    <View style={styles.wrap}>
      <Pressable
        style={styles.head}
        onPress={() => setChoice(!open)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`한 주의 기록${summary ? `, ${summary}` : ""}. ${open ? "접기" : "펼치기"}`}
      >
        <View style={styles.headText}>
          <Text style={styles.title}>한 주의 기록</Text>
          {summary ? <Text style={styles.summary}>{summary}</Text> : null}
        </View>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={20} color={colors.textMuted} />
      </Pressable>
      {open ? <View style={styles.body}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.md, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.md },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", minHeight: 44, gap: spacing.md },
  headText: { flex: 1, gap: spacing.xs },
  title: { ...font.section, color: colors.text },
  summary: { ...font.caption, color: colors.textMuted },
  body: { gap: spacing.lg, padding: spacing.md, borderRadius: radius.card, backgroundColor: colors.background },
});
