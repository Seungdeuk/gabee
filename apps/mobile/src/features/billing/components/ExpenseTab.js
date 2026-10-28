import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import ListItem from "@/shared/components/ListItem";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { createExpense, deleteExpense, getExpenses } from "../api";
import { formatMoneyInput, PAGE_SIZE, parseWon, remaining, won } from "../format";
import TagBadge from "./TagBadge";

/**
 * 지출 추가와 내역. 낸 사람은 로그인한 나로 서버가 정하고, 삭제는 소프트 삭제다.
 * 누구 몫으로 나눌지(대상 태그)는 정산 탭의 "정산하기"에서 정한다. 그 전까지는 가족 전체로 나눈다.
 * @param {{ month: string, notify: (text: string, isError?: boolean) => void }} props
 */
export default function ExpenseTab({ month, notify }) {
  const loadList = useCallback(() => getExpenses(month), [month]);
  const list = useResource(loadList);

  const [open, setOpen] = useState(false); // 지출 추가 폼은 "+ 지출 추가"를 눌렀을 때만 보인다
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE); // 내역은 5개씩 더보기

  useEffect(() => setShown(PAGE_SIZE), [month]);

  const closeForm = () => {
    setOpen(false);
    setTitle("");
    setAmount("");
  };

  const submit = async () => {
    const value = parseWon(amount);
    if (!title.trim()) return notify("항목을 입력해 주세요", true);
    if (!(value > 0)) return notify("금액은 1원 이상의 정수로 입력해 주세요", true);
    const date = `${month}-${String(new Date().getDate()).padStart(2, "0")}`;
    try {
      await createExpense({ title: title.trim(), amount: value, date });
      closeForm();
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
      {open ? (
        <Card tone="white">
          <Field label="항목" value={title} onChangeText={setTitle} placeholder="예: 장보기" />
          <Field
            label="금액 (원)"
            value={amount}
            onChangeText={(text) => setAmount(formatMoneyInput(text))}
            placeholder="숫자만"
            keyboardType="numeric"
          />
          <Text style={styles.caption}>낸 사람은 로그인한 나로 기록돼요.</Text>
          <Text style={styles.caption}>{"누구 몫인지는 정산 탭의 \"정산하기\"에서 정해요."}</Text>
          <View style={styles.formButtons}>
            <View style={styles.formButton}>
              <Button variant="secondary" label="취소" onPress={closeForm} />
            </View>
            <View style={styles.formButton}>
              <Button label="지출 추가" onPress={submit} />
            </View>
          </View>
        </Card>
      ) : (
        <Button label="+ 지출 추가" onPress={() => setOpen(true)} />
      )}

      <SectionTitle title={`${month} 내역`} />
      <Card tone="white">
        {list.loading && !list.data ? <Text style={styles.muted}>불러오는 중…</Text> : null}
        {list.data && list.data.length === 0 ? <Text style={styles.muted}>이 달 지출이 없어요</Text> : null}
        {(list.data ?? []).slice(0, shown).map((e) => (
          <ListItem
            key={e.id}
            icon="receipt-outline"
            tone="blue"
            title={e.title}
            subtitle={`${e.date} · ${e.paid_by_name} 결제 · ${e.split_among.length}명이 나눔`}
            right={
              <View style={styles.right}>
                <Text style={styles.amount}>{won(e.amount)}</Text>
                <View style={styles.actions}>
                  {e.subscription_id ? <Tag label="구독" tone="blue" /> : null}
                  <TagBadge tag={e.target_tag} settled={e.settled} />
                  <Button small variant="ghost" label="삭제" a11yLabel={`${e.title} 삭제`} onPress={() => remove(e.id)} />
                </View>
              </View>
            }
          />
        ))}
        {(list.data?.length ?? 0) > PAGE_SIZE ? (
          <View style={styles.moreRow}>
            {remaining(list.data.length, shown) > 0 ? (
              <Button
                small
                variant="secondary"
                label={`더보기 (남은 ${remaining(list.data.length, shown)}개)`}
                onPress={() => setShown(shown + PAGE_SIZE)}
              />
            ) : null}
            {shown > PAGE_SIZE ? <Button small variant="ghost" label="접기" onPress={() => setShown(PAGE_SIZE)} /> : null}
          </View>
        ) : null}
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 20 },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  right: { alignItems: "flex-end", gap: 6, maxWidth: "62%" },
  actions: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", flexWrap: "wrap", gap: 6 },
  formButtons: { flexDirection: "row", gap: 10 },
  formButton: { flex: 1 },
  moreRow: { flexDirection: "row", justifyContent: "center", gap: 8, paddingTop: 8 },
  amount: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
});
