import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import { colors, font } from "@/theme";

export const CARRIERS = [
  { key: "skt", label: "SKT" },
  { key: "kt", label: "KT" },
  { key: "lgu", label: "LG U+" },
  { key: "mvno", label: "알뜰폰" },
  { key: "other", label: "기타" },
];

/**
 * OTT·통신비 항목 입력 양식(추가·수정 공용). 월 금액과 결제일은 비워 둘 수 있다.
 * 금액은 사용자가 입력한 값만 저장하고, 가족 할인 금액은 계산하지 않는다.
 * @param {{ kind: "ott" | "telecom", initial?: import("../api").Subscription, busy?: boolean, onSubmit: (values: { name: string, carrier: string | null, monthly_fee: number | null, billing_day: number | null }) => void, onCancel: () => void, notify: (text: string, isError?: boolean) => void }} props
 */
export default function SubscriptionForm({ kind, initial, busy = false, onSubmit, onCancel, notify }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [carrier, setCarrier] = useState(initial?.carrier ?? null);
  const [fee, setFee] = useState(initial?.monthly_fee == null ? "" : String(initial.monthly_fee));
  const [day, setDay] = useState(initial?.billing_day == null ? "" : String(initial.billing_day));
  const editing = Boolean(initial);
  const subject = kind === "ott" ? "OTT" : "통신비";

  const submit = () => {
    if (!name.trim()) return notify("이름을 입력해 주세요", true);
    if (fee.trim() && !/^\d+$/.test(fee.trim())) return notify("월 금액은 숫자만 입력해 주세요", true);
    if (day.trim() && !(/^\d+$/.test(day.trim()) && Number(day) >= 1 && Number(day) <= 31)) {
      return notify("결제일은 1~31 사이 숫자로 입력해 주세요", true);
    }
    onSubmit({
      name: name.trim(),
      carrier: kind === "telecom" ? carrier : null,
      monthly_fee: fee.trim() ? Number(fee.trim()) : null,
      billing_day: day.trim() ? Number(day.trim()) : null,
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
      <Field label="월 금액 (원, 선택)" value={fee} onChangeText={setFee} placeholder="숫자만" keyboardType="numeric" />
      <Field label="매월 결제일 (1~31, 선택)" value={day} onChangeText={setDay} placeholder="예: 5" keyboardType="numeric" />
      <Text style={styles.caption}>할인 금액은 계산하지 않아요. 입력한 금액을 그대로 합산해요.</Text>
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
