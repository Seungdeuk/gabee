import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import WheelPicker from "@/shared/components/WheelPicker";
import { colors, font } from "@/theme";

import { dayOptions, expenseDate, formatMoneyInput, parseDayInput, quickDays } from "../format";

/**
 * 지출 입력 폼(추가와 수정에 같이 쓴다): 항목, 금액, 날짜(보고 있는 달 안에서 오늘·어제 빠른 선택과 일 휠).
 * 값 검사는 부르는 쪽이 한다. 폼의 입력 상태는 폼이 갖고, 누르면 onSubmit 에 한꺼번에 넘긴다.
 * @param {{
 *   month: string,
 *   initial: { title: string, amount: number | string, day: number },
 *   captions?: string[],
 *   submitLabel: string,
 *   onSubmit: (values: { title: string, amount: string, day: number }) => void,
 *   onCancel: () => void,
 * }} props amount 는 입력칸 글자(쉼표 포함)로 넘어간다
 */
export default function ExpenseForm({ month, initial, captions = [], submitLabel, onSubmit, onCancel }) {
  const [title, setTitle] = useState(initial.title);
  const [amount, setAmount] = useState(formatMoneyInput(initial.amount));
  const [day, setDay] = useState(initial.day);

  return (
    <Card tone="white">
      <Field label="항목" value={title} onChangeText={setTitle} placeholder="예: 장보기" />
      <Field label="금액 (원)" value={amount} onChangeText={(text) => setAmount(formatMoneyInput(text))} placeholder="숫자만" keyboardType="numeric" />
      <View style={styles.dateHead}>
        <Text style={styles.label}>날짜</Text>
        <Text style={styles.dateValue} testID="expense-date">
          {expenseDate(month, day)}
        </Text>
      </View>
      <View style={styles.quick}>
        {quickDays(month).map((q) => (
          <Button key={q.label} small variant="secondary" selected={day === q.day} label={q.label} a11yLabel={`${q.label}(${q.day}일)로 정하기`} onPress={() => setDay(q.day)} />
        ))}
      </View>
      <View style={styles.wheel}>
        <WheelPicker label="일" value={day} options={dayOptions(month)} parseInput={(text) => parseDayInput(month, text)} onChange={setDay} testID="expense-day" />
      </View>
      {captions.map((text) => (
        <Text key={text} style={styles.caption}>
          {text}
        </Text>
      ))}
      <View style={styles.buttons}>
        <View style={styles.button}>
          <Button variant="secondary" label="취소" onPress={onCancel} />
        </View>
        <View style={styles.button}>
          <Button label={submitLabel} onPress={() => onSubmit({ title, amount, day })} />
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  caption: { ...font.caption, color: colors.textMuted },
  label: { ...font.caption, color: colors.text, fontWeight: "600" },
  dateHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  dateValue: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
  quick: { flexDirection: "row", gap: 8 },
  wheel: { alignItems: "center" },
  buttons: { flexDirection: "row", gap: 10 },
  button: { flex: 1 },
});
