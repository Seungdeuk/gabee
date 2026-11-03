import { useCallback } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getSettlement } from "../api";
import { won } from "../format";

/**
 * 지갑 탭 정산 요약: 이번 달 남은 잔액과 보내야 할 송금 수. 누르면 정산 구역으로 간다.
 * @param {{ month: string, refreshKey?: number, onOpen: () => void }} props
 */
export default function SettleSummary({ month, refreshKey, onOpen }) {
  const load = useCallback(() => getSettlement(month), [month]);
  const { data } = useResource(load, refreshKey);
  if (!data) return null;
  const remaining = data.balances.reduce((a, b) => a + b.remaining, 0);
  const transfers = data.transfers?.length ?? 0;
  return (
    <Pressable onPress={onOpen} accessibilityRole="button" accessibilityLabel="정산 보러 가기" testID="settle-summary">
      <Card tone="white">
        <View style={styles.row}>
          <View style={styles.text}>
            <Text style={styles.label}>{month} 정산</Text>
            <Text style={styles.value}>{transfers > 0 ? `보낼 돈 ${transfers}건` : "보낼 돈이 없어요"}</Text>
            <Text style={styles.caption}>남은 잔액 합계 {won(remaining)}</Text>
          </View>
          <Text style={styles.go}>›</Text>
        </View>
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  text: { flex: 1, gap: 2 },
  label: { ...font.caption, color: colors.textMuted, fontWeight: "600" },
  value: { ...font.h1, color: colors.text },
  caption: { ...font.caption, color: colors.textSub },
  go: { fontSize: 28, color: colors.textMuted },
});
