import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { createExpense, deleteExpense, getExpenses } from "../api";
import { parseWon, won } from "../format";
import TagBadge from "./TagBadge";

/**
 * 지출 추가와 내역. 낸 사람은 로그인한 나로 서버가 정하고, 삭제는 소프트 삭제다.
 * 누구 몫으로 나눌지(대상 태그)는 정산 탭의 "정산하기"에서 정한다. 그 전까지는 가족 전체로 나눈다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function ExpenseTab({ month, notify }) {
  const loadList = useCallback(() => getExpenses(month), [month]);
  const list = useResource(loadList);

  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");

  const submit = async () => {
    const value = parseWon(amount);
    if (!title.trim()) return notify("항목을 입력해 주세요", true);
    if (!(value > 0)) return notify("금액은 1원 이상의 정수로 입력해 주세요", true);
    const date = `${month}-${String(new Date().getDate()).padStart(2, "0")}`;
    try {
      await createExpense({ title: title.trim(), amount: value, date });
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
        <Text style={styles.caption}>낸 사람은 로그인한 나로 기록돼요.</Text>
        <Text style={styles.caption}>{"누구 몫인지는 정산 탭의 \"정산하기\"에서 정해요."}</Text>
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
                <TagBadge tag={e.target_tag} settled={e.settled} />
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
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  right: { alignItems: "flex-end", gap: 6 },
  amount: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
});
