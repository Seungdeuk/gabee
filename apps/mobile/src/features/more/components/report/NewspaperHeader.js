import { StyleSheet, Text, View } from "react-native";

import { colors, font, spacing } from "@/theme";

import { REPORTER_GREETING } from "../../news/newsView";
import WeekSwitcher from "./WeekSwitcher";

/**
 * 신문형 머리글: 호수 · 제호("우리 가족 뉴스") · 가비 기자 인사, 그 아래 주 이동 줄.
 * 호수는 서버가 준 값만 보인다(없으면 줄을 비운다).
 * @param {{
 *   issue: string | null,
 *   range: { title: string, label: string, offset: number },
 *   canPrev: boolean,
 *   canNext: boolean,
 *   onPrev: () => void,
 *   onNext: () => void,
 *   onCurrent: () => void,
 * }} props
 * @returns {import("react").ReactElement}
 */
export default function NewspaperHeader({ issue, range, canPrev, canNext, onPrev, onNext, onCurrent }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.masthead}>
        <View style={styles.rule} />
        {issue ? <Text style={styles.issue}>{issue}</Text> : null}
        <Text style={styles.name} accessibilityRole="header">
          우리 가족 뉴스
        </Text>
        <Text style={styles.greeting}>{REPORTER_GREETING}</Text>
        <View style={styles.rule} />
      </View>
      <WeekSwitcher range={range} canPrev={canPrev} canNext={canNext} onPrev={onPrev} onNext={onNext} onCurrent={onCurrent} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  masthead: { alignItems: "center", gap: spacing.xs },
  rule: { alignSelf: "stretch", height: 1, backgroundColor: colors.border },
  issue: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily, marginTop: spacing.sm },
  name: { ...font.page, color: colors.text },
  greeting: { ...font.caption, color: colors.textMuted, marginBottom: spacing.sm },
});
