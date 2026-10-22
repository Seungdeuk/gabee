import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { createExpense, deleteExpense, getExpenses, getMembers } from "../api";
import { parseWon, won } from "../format";

/**
 * 지출 추가와 내역. 낸 사람과 나눌 사람을 고르고, 삭제는 소프트 삭제다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function ExpenseTab({ month, notify }) {
  const loadList = useCallback(() => getExpenses(month), [month]);
  const list = useResource(loadList);
  const members = useResource(getMembers);

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [payer, setPayer] = useState(null);
  const [split, setSplit] = useState(null); // null 이면 전원

  const people = members.data ?? [];
  const payerId = payer ?? people[0]?.id ?? null;
  const splitIds = split ?? people.map((m) => m.id);

  const toggle = (id) => setSplit(splitIds.includes(id) ? splitIds.filter((x) => x !== id) : [...splitIds, id]);

  const submit = async () => {
    const won_ = parseWon(amount);
    if (!title.trim()) return notify("항목을 입력해 주세요", true);
    if (!(won_ > 0)) return notify("금액은 1원 이상의 정수로 입력해 주세요", true);
    if (splitIds.length === 0) return notify("나눌 사람을 한 명 이상 골라 주세요", true);
    const date = `${month}-${String(new Date().getDate()).padStart(2, "0")}`;
    try {
      await createExpense({ title: title.trim(), amount: won_, date, paid_by: payerId, split_among: splitIds });
      setTitle("");
      setAmount("");
      notify("지출을 추가했어요");
      await list.reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  const remove = async (id) => {
    try {
      await deleteExpense(id);
      notify("삭제했어요 (기록은 남아 있어요)");
      await list.reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  return (
    <View style={styles.wrap}>
      <SectionTitle title="지출 추가" />
      <Card tone="white">
        <Field label="항목" value={title} onChangeText={setTitle} placeholder="예: 장보기" />
        <Field label="금액 (원)" value={amount} onChangeText={setAmount} placeholder="숫자만" keyboardType="numeric" />
        <Text style={styles.label}>낸 사람</Text>
        <View style={styles.chips}>
          {people.map((m) => (
            <Button key={m.id} small variant="secondary" label={m.name} a11yLabel={`낸 사람 ${m.name}`} selected={payerId === m.id} onPress={() => setPayer(m.id)} />
          ))}
        </View>
        <Text style={styles.label}>나눌 사람</Text>
        <View style={styles.chips}>
          {people.map((m) => (
            <Button key={m.id} small variant="secondary" label={m.name} a11yLabel={`나눌 사람 ${m.name}`} selected={splitIds.includes(m.id)} onPress={() => toggle(m.id)} />
          ))}
        </View>
        <Button label="지출 추가" onPress={submit} />
      </Card>

      <SectionTitle title={`${month} 내역`} />
      <Card tone="white">
        {list.loading && !list.data ? <Text style={styles.muted}>불러오는 중…</Text> : null}
        {list.data && list.data.length === 0 ? <Text style={styles.muted}>이 달 지출이 없어요</Text> : null}
        {(list.data ?? []).map((e) => (
          <ListItem
            key={e.id}
            icon="receipt-outline"
            tone="blue"
            title={e.title}
            subtitle={`${e.date} · ${e.paid_by_name} 결제 · ${e.split_among.length}명이 나눔`}
            right={
              <View style={styles.right}>
                <Text style={styles.amount}>{won(e.amount)}</Text>
                <Button small variant="ghost" label="삭제" a11yLabel={`${e.title} 삭제`} onPress={() => remove(e.id)} />
              </View>
            }
          />
        ))}
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 20 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  right: { alignItems: "flex-end", gap: 6 },
  amount: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
});
