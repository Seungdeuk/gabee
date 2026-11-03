import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 숫자 띠 한 칸: 라벨 + 큰 숫자 + 단위. value 가 null 이면 "–" 로 보이고 접근성 라벨은 nullText.
 * @param {{ label: string, value: number | null, unit: string, nullText?: string, children?: import("react").ReactNode }} props
 * @returns {import("react").ReactElement}
 */
function Cell({ label, value, unit, nullText = "불러오지 못했어요", children }) {
  const failed = value === null;
  return (
    <View
      style={styles.cell}
      accessible
      accessibilityLabel={failed ? `${label}, ${nullText}` : `${label}, ${value}${unit}`}
    >
      <Text style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={styles.value}>{failed ? "–" : value}</Text>
        {failed ? null : <Text style={styles.unit}>{unit}</Text>}
      </View>
      {children}
    </View>
  );
}

/**
 * 공유 일정·완료한 할 일·공유한 문서 숫자 띠(흰 카드 한 장, 세 칸)와 아래 설명 한 줄.
 * @param {{ sharedCount: number, todoDone: number, todoTotal: number, docCount: number | null, docsStatus?: "ok" | "loading" | "failed", isCurrent: boolean }} props
 * @returns {import("react").ReactElement}
 */
export default function StatBand({ sharedCount, todoDone, todoTotal, docCount, docsStatus, isCurrent }) {
  const ratio = todoTotal > 0 ? Math.min(todoDone / todoTotal, 1) : 0;
  return (
    <View style={styles.wrap}>
      <View style={styles.card}>
        <Cell label="공유 일정" value={sharedCount} unit="건" />
        <View style={styles.line} />
        <Cell label="완료한 할 일" value={todoDone} unit={`/${todoTotal}건`}>
          <View style={styles.track}>
            <View style={[styles.fill, { width: `${Math.round(ratio * 100)}%` }]} />
          </View>
        </Cell>
        <View style={styles.line} />
        <Cell
          label="공유한 문서"
          value={docCount}
          unit="건"
          nullText={docsStatus === "loading" ? "불러오는 중" : "불러오지 못했어요"}
        />
      </View>
      <Text style={styles.note}>
        {isCurrent
          ? "완료한 할 일은 이번 주 날짜의 공유 할 일 기준이에요."
          : "완료한 할 일은 그 주 날짜의 공유 할 일 기준이에요."}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  card: {
    flexDirection: "row",
    alignItems: "stretch",
    paddingVertical: spacing.lg,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  cell: { flex: 1, alignItems: "center", gap: spacing.xs, paddingHorizontal: spacing.xs },
  line: { width: 1, backgroundColor: colors.divider },
  label: { ...font.caption, color: colors.textMuted },
  valueRow: { flexDirection: "row", alignItems: "baseline" },
  value: { ...font.page, color: colors.text },
  unit: { ...font.caption, color: colors.textSub },
  track: {
    alignSelf: "stretch",
    height: 4,
    marginHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.divider,
    overflow: "hidden",
  },
  fill: { height: 4, backgroundColor: colors.success },
  note: { ...font.caption, color: colors.textMuted },
});
