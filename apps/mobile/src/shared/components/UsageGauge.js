import { StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

/**
 * 오늘 AI 사용량 게이지 바. 쓴 만큼 채워지고 오른쪽에 "N% 사용됨"을 보인다(횟수는 보이지 않는다).
 * 거의 다 썼으면 색과 함께 글도 보인다(색만으로 구분하지 않는다).
 * @param {{ gauges: { key: string, label: string, ratio: number, percent: number, high: boolean }[] }} props usageGauges 결과(비어 있으면 아무것도 그리지 않는다)
 * @returns {import("react").ReactElement | null}
 */
export default function UsageGauge({ gauges }) {
  if (gauges.length === 0) return null;
  return (
    <View style={styles.box}>
      {gauges.map((g) => (
        <View key={g.key} style={styles.item}>
          <View style={styles.row}>
            <Text style={styles.label}>{g.label}</Text>
            <Text style={styles.percent}>{`${g.percent}% 사용됨`}</Text>
          </View>
          <View
            style={styles.track}
            accessibilityRole="progressbar"
            accessibilityLabel={`${g.label} 오늘 사용량`}
            accessibilityValue={{ min: 0, max: 100, now: g.percent }}
          >
            <View style={[styles.fill, { width: `${g.percent}%`, backgroundColor: g.high ? colors.danger : colors.accent }]} />
          </View>
          {g.high ? <Text style={styles.high}>거의 다 썼어요</Text> : null}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: spacing.md },
  item: { gap: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  label: { ...font.caption, color: colors.textSub },
  track: { alignSelf: "stretch", height: 10, borderRadius: radius.pill, backgroundColor: colors.surfaceStrong, overflow: "hidden" },
  fill: { height: "100%", borderRadius: radius.pill },
  percent: { ...font.caption, color: colors.textSub },
  high: { ...font.caption, color: colors.danger },
});
