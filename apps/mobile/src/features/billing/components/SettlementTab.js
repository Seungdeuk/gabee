import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getSettlement, markPaid, undoPaid } from "../api";
import { won } from "../format";
import SettleForm from "./SettleForm";

/**
 * 비용 정산: 구성원별 잔액, 최소 송금 목록, 송금 완료 표시.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function SettlementTab({ month, notify }) {
  const load = useCallback(() => getSettlement(month), [month]);
  const { data, error, loading, reload } = useResource(load);

  const act = async (run, done) => {
    try {
      await run();
      notify(done);
      await reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "정산을 불러오지 못했어요"}</Text>;

  const balanceSum = data.balances.reduce((a, b) => a + b.balance, 0);
  const remainingSum = data.balances.reduce((a, b) => a + b.remaining, 0);

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <View style={styles.stats}>
          <Stat label="구성원" value={`${data.balances.length}명`} />
          <Stat label="잔액 합계" value={won(balanceSum)} testID="balance-sum" />
          <Stat label="남은 잔액 합계" value={won(remainingSum)} testID="remaining-sum" />
        </View>
      </Card>

      <SectionTitle title="구성원별 잔액" />
      <Card tone="white">
        {data.balances.map((b) => (
          <ListItem
            key={b.user_id}
            title={b.name}
            subtitle={`낸 돈 ${won(b.paid)} · 내 몫 ${won(b.share)}`}
            right={
              <View style={styles.amountBox}>
                <Text style={[styles.amount, b.balance < 0 ? styles.owe : styles.get]}>
                  {b.balance > 0 ? "+" : ""}
                  {won(b.balance)}
                </Text>
                <Text style={styles.caption}>남은 {won(b.remaining)}</Text>
              </View>
            }
          />
        ))}
      </Card>

      <SettleForm month={month} notify={notify} onSettled={reload} />

      <SectionTitle title="보낼 돈 (최소 송금)" />
      <Card tone="white">
        {data.transfers.length === 0 ? <Text style={styles.muted}>보낼 돈이 없어요</Text> : null}
        {data.transfers.map((t) => (
          <ListItem
            key={`${t.from_user_id}-${t.to_user_id}`}
            icon="swap-horizontal"
            tone="blue"
            title={`${t.from_name} → ${t.to_name}`}
            subtitle={won(t.amount)}
            right={
              <Button
                small
                label="송금 완료"
                a11yLabel={`${t.from_name} → ${t.to_name} 송금 완료`}
                onPress={() => act(() => markPaid(month, t), "송금 완료로 표시했어요")}
              />
            }
          />
        ))}
      </Card>

      <SectionTitle title="송금 완료" />
      <Card tone="white">
        {data.completed.length === 0 ? <Text style={styles.muted}>아직 없어요</Text> : null}
        {data.completed.map((p) => (
          <ListItem
            key={p.id}
            icon="checkmark-circle"
            tone="green"
            title={`${p.from_name} → ${p.to_name}`}
            subtitle={`✓ 완료 · ${won(p.amount)}`}
            right={
              <Button
                small
                variant="secondary"
                label="취소"
                a11yLabel={`${p.from_name} → ${p.to_name} 송금 취소`}
                onPress={() => act(() => undoPaid(p.id), "송금 완료를 취소했어요")}
              />
            }
          />
        ))}
      </Card>
    </View>
  );
}

function Stat({ label, value, testID }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.caption}>{label}</Text>
      <Text style={styles.statValue} testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 20 },
  stats: { flexDirection: "row", justifyContent: "space-between" },
  stat: { flex: 1, alignItems: "center", gap: 4 },
  statValue: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
  amountBox: { alignItems: "flex-end" },
  amount: { ...font.bodyStrong, fontWeight: "700" },
  owe: { color: colors.danger },
  get: { color: colors.success },
});
