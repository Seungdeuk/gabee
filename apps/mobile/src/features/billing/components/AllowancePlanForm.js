import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";
import { colors, font } from "@/theme";

import { parseWon, won } from "../format";

export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

/** @param {import("../api").AllowancePlan} plan @returns {string} 예: 매월 25일 · 30,000원 · 자동 지급 */
export function planText(plan) {
  const when = plan.cycle === "weekly" ? `매주 ${WEEKDAYS[plan.day]}요일` : `매월 ${plan.day}일`;
  return `${when} · ${won(plan.amount)} · ${plan.mode === "auto" ? "자동 지급" : "리마인드"}`;
}

/**
 * 고정 용돈 주기 입력(부모·그룹을 만든 사람). 자동 지급은 지급일이 지난 분을 장부에 입금으로 기록하고,
 * 리마인드는 지급자에게 "지급했어요" 를 누르라고 알린다. 돈이 실제로 오가지는 않는다(앱 안 장부).
 * @param {{ name: string, initial: import("../api").AllowancePlan | null, busy?: boolean, onSubmit: (body: object) => void, onCancel: () => void, notify: (text: string, isError?: boolean) => void }} props
 */
export default function AllowancePlanForm({ name, initial, busy = false, onSubmit, onCancel, notify }) {
  const [cycle, setCycle] = useState(initial?.cycle ?? "monthly");
  const [day, setDay] = useState(initial ? initial.day : 1);
  const [dayText, setDayText] = useState(String(initial && initial.cycle === "monthly" ? initial.day : 1));
  const [amount, setAmount] = useState(initial ? String(initial.amount) : "");
  const [mode, setMode] = useState(initial?.mode ?? "auto");

  const pickCycle = (next) => {
    setCycle(next);
    setDay(next === "weekly" ? 0 : 1);
    setDayText("1");
  };

  const submit = () => {
    const money = parseWon(amount);
    if (!(money > 0)) return notify("지급 금액은 1원 이상의 정수로 입력해 주세요", true);
    let when = day;
    if (cycle === "monthly") {
      when = parseWon(dayText);
      if (!(when >= 1 && when <= 31)) return notify("지급일은 1~31 사이 숫자로 입력해 주세요", true);
    }
    onSubmit({ cycle, day: when, amount: money, mode });
  };

  return (
    <View style={styles.box} testID={`plan-form-${name}`}>
      <Text style={styles.label}>주기</Text>
      <View style={styles.chips}>
        <Button small variant="secondary" selected={cycle === "monthly"} label="매월" a11yLabel={`${name} 주기 매월`} onPress={() => pickCycle("monthly")} />
        <Button small variant="secondary" selected={cycle === "weekly"} label="매주" a11yLabel={`${name} 주기 매주`} onPress={() => pickCycle("weekly")} />
      </View>
      {cycle === "weekly" ? (
        <View style={styles.chips}>
          {WEEKDAYS.map((w, i) => (
            <Button key={w} small variant="secondary" selected={day === i} label={w} a11yLabel={`${name} 지급 요일 ${w}`} onPress={() => setDay(i)} />
          ))}
        </View>
      ) : (
        <Field label="매월 지급일 (1~31)" value={dayText} onChangeText={setDayText} keyboardType="numeric" placeholder="예: 25" />
      )}
      <Field label="한 번에 지급하는 금액 (원)" value={amount} onChangeText={setAmount} keyboardType="numeric" placeholder="숫자만" />
      <Text style={styles.label}>지급 방식</Text>
      <View style={styles.chips}>
        <Button small variant="secondary" selected={mode === "auto"} label="자동 지급" a11yLabel={`${name} 자동 지급`} onPress={() => setMode("auto")} />
        <Button small variant="secondary" selected={mode === "remind"} label="리마인드" a11yLabel={`${name} 리마인드`} onPress={() => setMode("remind")} />
      </View>
      <Text style={styles.caption}>
        {mode === "auto"
          ? "지급일이 지나면 장부에 입금이 자동으로 기록돼요. 실제 송금은 직접 해 주세요."
          : "지급일이 되면 \"지급했어요\" 알림이 떠요. 누르면 장부에 입금이 기록돼요."}
      </Text>
      <View style={styles.actions}>
        <Button small variant="secondary" label="취소" a11yLabel={`${name} 주기 취소`} onPress={onCancel} />
        <Button small label="저장" a11yLabel={`${name} 주기 저장`} onPress={submit} disabled={busy} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 10, paddingTop: 4 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  caption: { ...font.caption, color: colors.textMuted },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
});
