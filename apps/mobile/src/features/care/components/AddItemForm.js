import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import SectionTitle from "@/shared/components/SectionTitle";
import TimePicker from "@/shared/components/TimePicker";
import { colors, font } from "@/theme";

import { addItem } from "../api";

const MODES = [
  { key: "yesno", label: "예/아니오" },
  { key: "number", label: "수치(목표)" },
  { key: "condition", label: "컨디션" },
];
const MEALS = [
  { key: "", label: "끼니 없음" },
  { key: "breakfast", label: "아침" },
  { key: "lunch", label: "점심" },
  { key: "dinner", label: "저녁" },
];

/**
 * 체크 항목 추가 양식(이름, 기록 방식, 단위·목표, 예정 시각 휠 선택기, 끼니).
 * @param {{ notify: (text: string, isError?: boolean) => void, onAdded: () => Promise<void> | void }} props
 */
export default function AddItemForm({ notify, onAdded }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState("yesno");
  const [unit, setUnit] = useState("");
  const [target, setTarget] = useState("");
  const [time, setTime] = useState("12:00");
  const [meal, setMeal] = useState("");

  const submit = async () => {
    if (!name.trim()) return notify("이름을 입력해 주세요", true);
    try {
      await addItem({
        name: name.trim(),
        mode,
        unit: mode === "number" ? unit.trim() : "",
        target: mode === "number" && target.trim() ? parseInt(target.trim(), 10) : null,
        scheduled_time: time,
        meal_type: mode === "yesno" && meal ? meal : null,
      });
      setName("");
      setUnit("");
      setTarget("");
      notify("항목을 추가했어요");
      await onAdded();
    } catch (e) {
      notify(e.message, true);
    }
  };

  return (
    <View style={styles.wrap}>
      <SectionTitle title="항목 추가" />
      <Card tone="white">
        <Field label="이름" value={name} onChangeText={setName} placeholder="예: 혈압 재기" />
        <Text style={styles.label}>기록 방식</Text>
        <View style={styles.options}>
          {MODES.map((m) => (
            <Button key={m.key} small variant="secondary" label={m.label} a11yLabel={`방식 ${m.label}`} selected={mode === m.key} onPress={() => setMode(m.key)} />
          ))}
        </View>
        {mode === "number" ? (
          <View style={styles.line}>
            <Field style={styles.grow} label="단위" value={unit} onChangeText={setUnit} placeholder="예: ml" />
            <Field style={styles.grow} label="목표" value={target} onChangeText={setTarget} placeholder="숫자" keyboardType="numeric" />
          </View>
        ) : null}
        <TimePicker label="예정 시각" value={time} onChange={setTime} />
        {mode === "yesno" ? (
          <>
            <Text style={styles.label}>끼니 (식단 추천용)</Text>
            <View style={styles.options}>
              {MEALS.map((m) => (
                <Button key={m.key || "none"} small variant="secondary" label={m.label} a11yLabel={`끼니 ${m.label}`} selected={meal === m.key} onPress={() => setMeal(m.key)} />
              ))}
            </View>
          </>
        ) : null}
        <Button label="항목 추가" onPress={submit} />
      </Card>
    </View>
  );
}


const styles = StyleSheet.create({
  wrap: { gap: 16 },
  grow: { flex: 1 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  line: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  caption: { ...font.caption, color: colors.textMuted },
});
