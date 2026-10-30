import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import { colors, font } from "@/theme";

import { formatMoneyInput, stripMoney } from "../format";

export const CARRIERS = [
  { key: "skt", label: "SKT" },
  { key: "kt", label: "KT" },
  { key: "lgu", label: "LG U+" },
  { key: "mvno", label: "알뜰폰" },
  { key: "other", label: "기타" },
];

/**
 * OTT·통신비 항목 입력 양식(추가·수정 공용). 월 청구 금액·결합 할인 금액·결제일은 비워 둘 수 있다.
 * 청구서를 보고 처음 한 번(또는 바뀔 때) 직접 입력한 값만 저장하고 할인 금액은 계산하지 않는다.
 * 결제한 사람과 나눌 사람은 "이번 달 구독료 지출 만들기"가 만드는 지출에 쓰인다(나눌 사람 기본은 가족 전체).
 * @param {{ kind: "ott" | "telecom", presetName?: string, initial?: import("../api").Subscription, people: { id: string, name: string }[], meId: string | null, busy?: boolean, onSubmit: (values: object) => void, onCancel: () => void, notify: (text: string, isError?: boolean) => void }} props
 */
export default function SubscriptionForm({ kind, initial, presetName = "", people, meId, busy = false, onSubmit, onCancel, notify }) {
  const [name, setName] = useState(initial?.name ?? presetName);
  const [carrier, setCarrier] = useState(initial?.carrier ?? null);
  const [fee, setFee] = useState(initial?.monthly_fee == null ? "" : formatMoneyInput(initial.monthly_fee));
  const [discount, setDiscount] = useState(initial?.discount_amount == null ? "" : formatMoneyInput(initial.discount_amount));
  const [day, setDay] = useState(initial?.billing_day == null ? "" : String(initial.billing_day));
  const [payer, setPayer] = useState(initial ? initial.payer_id : meId); // 새 항목은 등록하는 나
  const [split, setSplit] = useState(initial?.split_among?.length ? initial.split_among : people.map((p) => p.id));
  const editing = Boolean(initial);
  const subject = kind === "ott" ? "OTT" : "통신비";

  const toggleSplit = (id) => setSplit(split.includes(id) ? split.filter((x) => x !== id) : [...split, id]);

  const submit = () => {
    if (!name.trim()) return notify("이름을 입력해 주세요", true);
    if (stripMoney(fee) && !/^\d+$/.test(stripMoney(fee))) return notify("월 청구 금액은 숫자만 입력해 주세요", true);
    if (stripMoney(discount) && !/^\d+$/.test(stripMoney(discount))) return notify("결합 할인 금액은 숫자만 입력해 주세요", true);
    if (day.trim() && !(/^\d+$/.test(day.trim()) && Number(day) >= 1 && Number(day) <= 31)) {
      return notify("결제일은 1~31 사이 숫자로 입력해 주세요", true);
    }
    if (split.length === 0) return notify("나눌 사람을 한 명 이상 골라 주세요", true);
    onSubmit({
      name: name.trim(),
      carrier: kind === "telecom" ? carrier : null,
      monthly_fee: stripMoney(fee) ? Number(stripMoney(fee)) : null,
      discount_amount: stripMoney(discount) ? Number(stripMoney(discount)) : null,
      billing_day: day.trim() ? Number(day.trim()) : null,
      payer_id: payer,
      split_among: split.length === people.length ? [] : split, // 전원이면 비워서 가족 전체로 저장
    });
  };

  return (
    <Card tone="white" testID="subscription-form">
      <Text style={styles.title}>
        {subject} {editing ? "수정" : "추가"}
      </Text>
      <Field label="이름" value={name} onChangeText={setName} placeholder={kind === "ott" ? "예: 왓챠" : "예: 우리 집 통신비"} />
      {kind === "telecom" ? (
        <View style={styles.block}>
          <Text style={styles.label}>통신사</Text>
          <View style={styles.chips}>
            {CARRIERS.map((c) => (
              <Button
                key={c.key}
                small
                variant="secondary"
                selected={carrier === c.key}
                label={c.label}
                a11yLabel={`통신사 ${c.label}`}
                onPress={() => setCarrier(carrier === c.key ? null : c.key)}
              />
            ))}
          </View>
        </View>
      ) : null}
      <Field label="월 청구 금액 (원, 청구서 기준, 선택)" value={fee} onChangeText={(text) => setFee(formatMoneyInput(text))} placeholder="숫자만" keyboardType="numeric" />
      <Field label="결합 할인 금액 (원, 청구서 기준, 선택)" value={discount} onChangeText={(text) => setDiscount(formatMoneyInput(text))} placeholder="숫자만" keyboardType="numeric" />
      <Field label="매월 결제일 (1~31, 선택)" value={day} onChangeText={setDay} placeholder="예: 5" keyboardType="numeric" />

      <View style={styles.block}>
        <Text style={styles.label}>결제한 사람</Text>
        <View style={styles.chips}>
          {people.map((p) => (
            <Button
              key={p.id}
              small
              variant="secondary"
              selected={payer === p.id}
              label={p.name}
              a11yLabel={`결제한 사람 ${p.name}`}
              onPress={() => setPayer(payer === p.id ? null : p.id)}
            />
          ))}
        </View>
      </View>
      <View style={styles.block}>
        <Text style={styles.label}>나눌 사람 (기본 가족 전체)</Text>
        <View style={styles.chips}>
          {people.map((p) => (
            <Button
              key={p.id}
              small
              variant="secondary"
              selected={split.includes(p.id)}
              label={p.name}
              a11yLabel={`구독 나눌 사람 ${p.name}`}
              onPress={() => toggleSplit(p.id)}
            />
          ))}
        </View>
      </View>
      <Text style={styles.caption}>청구서를 보고 처음 한 번(또는 바뀔 때) 직접 입력해 주세요. 할인은 계산하지 않고, 지출은 월 청구 금액으로 만들어요. 결제한 사람이 없으면 지출을 만들지 않아요.</Text>
      <View style={styles.actions}>
        <Button small variant="secondary" label="취소" a11yLabel={`${subject} ${editing ? "수정" : "추가"} 취소`} onPress={onCancel} />
        <Button small label="저장" a11yLabel={`${subject} ${editing ? "수정" : "추가"} 저장`} onPress={submit} disabled={busy} />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  block: { gap: 6 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  caption: { ...font.caption, color: colors.textMuted },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
});
