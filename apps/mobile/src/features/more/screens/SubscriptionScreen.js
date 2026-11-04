import { useRouter } from "expo-router";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import UsageGauge from "@/shared/components/UsageGauge";
import { colors, font, radius, spacing } from "@/theme";

import { SUBSCRIPTION_PLAN_NOTE, SUBSCRIPTION_USAGE_NOTE, SUBSCRIPTION_USAGE_UNAVAILABLE } from "../subscriptionCopy";
import { useAiUsage } from "../useAiUsage";

/**
 * 마이 > 구독 관리: 가비 AI 오늘 사용량을 게이지로 보여 준다. 요금제·결제는 아직 없어 안내 글만 둔다.
 * @returns {import("react").ReactElement}
 */
export default function SubscriptionScreen() {
  const router = useRouter();
  const usage = useAiUsage();
  return (
    <Screen
      title="구독 관리"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          오늘 사용량
        </Text>
        <View style={styles.card}>
          {usage.status === "loading" ? <ActivityIndicator color={colors.accent} /> : null}
          {usage.status === "ready" ? <UsageGauge gauges={usage.gauges} /> : null}
          {usage.status === "unavailable" ? <Text style={styles.sub}>{SUBSCRIPTION_USAGE_UNAVAILABLE}</Text> : null}
          <Text style={styles.sub}>{SUBSCRIPTION_USAGE_NOTE}</Text>
        </View>
      </View>
      <View style={styles.section}>
        <Text style={styles.sectionTitle} accessibilityRole="header">
          요금제
        </Text>
        <View style={styles.card}>
          <Text style={styles.sub}>{SUBSCRIPTION_PLAN_NOTE}</Text>
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  section: { gap: spacing.sm },
  sectionTitle: { ...font.cardTitle, color: colors.text },
  card: { gap: spacing.md, padding: spacing.lg, borderRadius: radius.card, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  sub: { ...font.caption, color: colors.textSub },
});
