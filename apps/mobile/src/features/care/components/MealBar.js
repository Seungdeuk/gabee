import { StyleSheet, Text, View } from "react-native";

import { formatTime } from "@/shared/components/TimePicker";
import { colors, font } from "@/theme";

// 끼니 하나의 상태를 짧은 말과 색으로 보여 준다. 누락은 경고색이 아니라 크림색이다(미기록은 건강 이상이 아니다).
const LOOK = {
  done: { bg: colors.successSoft, fg: colors.success },
  skipped: { bg: colors.honeySoft, fg: colors.textMuted },
  missing: { bg: colors.surfaceStrong, fg: colors.text },
  due: { bg: colors.peach, fg: colors.text },
  upcoming: { bg: colors.card, fg: colors.textSub, border: colors.border },
};

/** @param {import("../api").MealStatus} m @returns {string} */
function statusText(m) {
  const no = m.answer === "no";
  if (m.status === "done") return "✓ 먹었어요";
  if (m.status === "skipped") return "건너뜀";
  if (m.status === "missing") return no ? "안 먹었어요" : "미기록";
  if (m.status === "due") return no ? "안 먹었어요" : "지금이에요";
  return `${formatTime(m.scheduled_time)} 예정`;
}

/**
 * 아침·점심·저녁 상태를 한눈에 본다. large 는 현황판용으로 칸과 글자를 키운다(위쪽 띠 테두리도 없앤다).
 * @param {{ meals: import("../api").MealStatus[], large?: boolean }} props
 */
export default function MealBar({ meals, large = false }) {
  if (!meals.length) return null;
  return (
    <View style={[styles.bar, large && styles.barLarge]} accessibilityRole="summary" accessibilityLabel="오늘의 끼니 상태" testID="meal-bar">
      {meals.map((m) => {
        const look = LOOK[m.status];
        return (
          <View
            key={m.meal}
            testID={`meal-${m.meal}`}
            accessibilityLabel={`${m.label} ${statusText(m)}`}
            style={[styles.cell, large && styles.cellLarge, { backgroundColor: look.bg, borderColor: look.border ?? look.bg }]}
          >
            <Text style={[styles.label, large && styles.labelLarge]}>{m.label}</Text>
            <Text style={[styles.status, large && styles.statusLarge, { color: look.fg }]}>{statusText(m)}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: "row", gap: 8, paddingHorizontal: 20, paddingVertical: 10, backgroundColor: colors.background, borderBottomWidth: 1, borderBottomColor: colors.divider },
  cell: { flex: 1, borderRadius: 14, borderWidth: 1, paddingVertical: 8, paddingHorizontal: 6, alignItems: "center", gap: 2 },
  barLarge: { paddingHorizontal: 0, paddingVertical: 0, borderBottomWidth: 0 },
  cellLarge: { paddingVertical: 18, gap: 6, borderRadius: 18 },
  labelLarge: { fontSize: 16 },
  statusLarge: { fontSize: 15, lineHeight: 20 },
  label: { fontSize: 12, fontWeight: "700", color: colors.text },
  status: { ...font.caption, fontWeight: "600", textAlign: "center" },
});
