import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { addAllowanceUse, getAllowances, setBudget } from "../api";
import { parseWon, won } from "../format";

/**
 * 용돈 관리: 자녀별 월 예산, 사용 기록 추가, 남은 금액. 남은 금액보다 큰 사용은 서버가 거절한다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function AllowanceTab({ month, notify }) {
  const load = useCallback(() => getAllowances(month), [month]);
  const { data, error, loading, reload } = useResource(load);

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "용돈을 불러오지 못했어요"}</Text>;
  if (data.length === 0) return <Text style={styles.muted}>자녀(부모 역할이 아닌 구성원)가 없어요</Text>;

  return (
    <View style={styles.wrap}>
      {data.map((c) => (
        <ChildAllowance key={c.child_id} item={c} month={month} notify={notify} onChanged={reload} />
      ))}
    </View>
  );
}

function ChildAllowance({ item, month, notify, onChanged }) {
  const [budget, setBudgetText] = useState(item.budget === null ? "" : String(item.budget));
  const [amount, setAmount] = useState("");
  const [memo, setMemo] = useState("");

  const run = async (fn, done, after) => {
    try {
      await fn();
      notify(done);
      after?.();
      await onChanged();
    } catch (e) {
      notify(e.message, true);
    }
  };

  const saveBudget = () => {
    const value = parseWon(budget);
    if (Number.isNaN(value)) return notify("예산은 0 이상의 정수로 입력해 주세요", true);
    run(() => setBudget(item.child_id, month, value), "예산을 저장했어요");
  };

  const saveUse = () => {
    const value = parseWon(amount);
    if (!(value > 0)) return notify("사용 금액은 1원 이상의 정수로 입력해 주세요", true);
    run(
      () => addAllowanceUse(item.child_id, { amount: value, memo }),
      "사용 기록을 추가했어요",
      () => {
        setAmount("");
        setMemo("");
      },
    );
  };

  const ratio = item.budget ? Math.min(1, item.used / item.budget) : 0;

  return (
    <Card tone="white">
      <View style={styles.head}>
        <View style={styles.grow}>
          <Text style={styles.name}>{item.name}</Text>
          <Text style={styles.caption}>
            {item.month} 예산 {item.budget === null ? "미설정" : won(item.budget)}
          </Text>
        </View>
        <View style={styles.remainBox}>
          <Text style={styles.caption}>남은 금액</Text>
          <Text style={[styles.remain, item.remaining > 0 ? styles.ok : styles.none]} testID={`remaining-${item.name}`}>
            {won(item.remaining)}
          </Text>
        </View>
      </View>
      <View style={styles.track}>
        <View style={[styles.fill, { width: `${ratio * 100}%` }]} />
      </View>
      <Text style={styles.caption}>사용 {won(item.used)}</Text>

      <View style={styles.line}>
        <Field style={styles.grow} value={budget} onChangeText={setBudgetText} placeholder={`${item.name} 예산(원)`} keyboardType="numeric" />
        <Button small label="예산 저장" a11yLabel={`${item.name} 예산 저장`} onPress={saveBudget} />
      </View>
      <View style={styles.line}>
        <Field style={styles.amountField} value={amount} onChangeText={setAmount} placeholder={`${item.name} 사용 금액`} keyboardType="numeric" />
        <Field style={styles.grow} value={memo} onChangeText={setMemo} placeholder="메모" />
        <Button small variant="secondary" label="기록" a11yLabel={`${item.name} 사용 기록`} onPress={saveUse} />
      </View>

      {item.uses.map((u) => (
        <Text key={u.id} style={styles.caption}>
          {u.date} · {u.memo || "사용"} · {won(u.amount)}
        </Text>
      ))}
    </Card>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
  name: { ...font.cardTitle, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  remainBox: { alignItems: "flex-end" },
  remain: { ...font.cardTitle },
  ok: { color: colors.success },
  none: { color: colors.danger },
  track: { height: 8, backgroundColor: colors.divider, borderRadius: 4, overflow: "hidden" },
  fill: { height: 8, backgroundColor: colors.success },
  line: { flexDirection: "row", alignItems: "center", gap: 8 },
  amountField: { width: 120 },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
});
