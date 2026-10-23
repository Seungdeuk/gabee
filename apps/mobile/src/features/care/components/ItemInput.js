import { useState } from "react";
import { StyleSheet, View } from "react-native";

import Button from "@/shared/components/Button";
import Field from "@/shared/components/Field";

import { putEntry } from "../api";

export const CONDITIONS = [
  { key: "good", label: "좋음" },
  { key: "normal", label: "보통" },
  { key: "bad", label: "나쁨" },
];

/** @param {import("../api").CareItem} item @returns {string} 기록한 값(예/아니오, 수치, 컨디션) */
export function entryText(item) {
  const e = item.entry;
  if (!e) return "기록 없음";
  if (e.skipped) return "건너뜀";
  if (item.mode === "yesno") return e.done ? "예" : "아니오";
  if (item.mode === "number") return `${e.number}${item.unit}`;
  return CONDITIONS.find((c) => c.key === e.condition)?.label ?? "";
}

/**
 * 항목 하나의 기록 입력: 예/아니오, 수치(목표 있음), 컨디션 중 항목의 기록 방식에 맞는 버튼·입력칸.
 * 지금 기록하는 것이든 지난 항목을 소급 입력하는 것이든 같은 입력을 쓴다.
 * @param {{ item: import("../api").CareItem, act: (run: () => Promise<unknown>, done?: string) => Promise<void>, notify: (text: string, isError?: boolean) => void, doneText?: string }} props
 */
export default function ItemInput({ item, act, notify, doneText }) {
  const [value, setValue] = useState(item.entry?.number == null ? "" : String(item.entry.number));

  if (item.mode === "yesno") {
    return (
      <View style={styles.options}>
        <Button small variant="secondary" label="예" a11yLabel={`${item.name} 예`} selected={item.entry?.done === true} onPress={() => act(() => putEntry(item.id, { done: true }), doneText)} />
        <Button small variant="secondary" label="아니오" a11yLabel={`${item.name} 아니오`} selected={item.entry?.done === false} onPress={() => act(() => putEntry(item.id, { done: false }), doneText)} />
      </View>
    );
  }
  if (item.mode === "condition") {
    return (
      <View style={styles.options}>
        {CONDITIONS.map((c) => (
          <Button key={c.key} small variant="secondary" label={c.label} a11yLabel={`${item.name} ${c.label}`} selected={item.entry?.condition === c.key} onPress={() => act(() => putEntry(item.id, { condition: c.key }), doneText)} />
        ))}
      </View>
    );
  }
  const save = () => {
    if (!/^\d+$/.test(value.trim())) return notify("숫자만 입력해 주세요", true);
    act(() => putEntry(item.id, { number: parseInt(value.trim(), 10) }), doneText ?? "저장했어요");
  };
  return (
    <View style={styles.line}>
      <Field style={styles.grow} value={value} onChangeText={setValue} placeholder={`${item.name} (${item.unit})`} keyboardType="numeric" />
      <Button small label="저장" a11yLabel={`${item.name} 저장`} onPress={save} />
    </View>
  );
}

const styles = StyleSheet.create({
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  line: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  grow: { flex: 1 },
});
