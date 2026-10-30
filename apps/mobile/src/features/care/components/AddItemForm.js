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
  { key: "yesno", label: "체크(했어요)" },
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
 * 체크 항목 추가. 평소에는 "+ 항목 추가" 버튼만 보이고, 누르면 이름과 예정 시각만 적는 간단한 양식이 펼쳐진다.
 * 이렇게 만든 항목은 매일 한 번 누르는 체크 항목이다. 수치·컨디션·끼니는 "자세히 설정"에서 고른다.
 * 저장에 성공하면 양식이 접히고, 실패하면 양식을 그대로 둔 채 양식 안에 오류를 보여 준다.
 * @param {{ notify: (text: string, isError?: boolean) => void, onAdded: () => Promise<void> | void }} props
 */
export default function AddItemForm({ notify, onAdded }) {
  const [open, setOpen] = useState(false);
  const [more, setMore] = useState(false); // 자세히 설정(기록 방식·단위·목표·끼니)
  const [name, setName] = useState("");
  const [mode, setMode] = useState("yesno");
  const [unit, setUnit] = useState("");
  const [target, setTarget] = useState("");
  const [time, setTime] = useState("12:00");
  const [meal, setMeal] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setOpen(false);
    setMore(false);
    setName("");
    setMode("yesno");
    setUnit("");
    setTarget("");
    setMeal("");
    setError(null);
  };

  const submit = async () => {
    if (!name.trim()) return setError("이름을 입력해 주세요");
    if (mode === "number" && target.trim() && !/^\d+$/.test(target.trim())) return setError("목표는 숫자만 입력해 주세요");
    setBusy(true);
    try {
      await addItem({
        name: name.trim(),
        mode,
        unit: mode === "number" ? unit.trim() : "",
        target: mode === "number" && target.trim() ? parseInt(target.trim(), 10) : null,
        scheduled_time: time,
        meal_type: mode === "yesno" && meal ? meal : null,
      });
      close();
      notify("항목을 추가했어요");
      await onAdded();
    } catch (e) {
      setError(e.message); // 양식은 열어 둔 채 이유를 양식 안에 보여 준다
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.wrap}>
      <SectionTitle title="항목 추가" />
      {open ? (
        <Card tone="white">
          <Field label="이름" value={name} onChangeText={setName} placeholder="예: 혈압약 먹기" />
          <TimePicker label="예정 시각" value={time} onChange={setTime} />
          <Text style={styles.caption}>추가한 항목은 매일 한 번 눌러서 체크해요.</Text>

          <Button small variant="secondary" label={more ? "자세히 설정 접기" : "자세히 설정"} onPress={() => setMore(!more)} />
          {more ? (
            <View style={styles.more}>
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
            </View>
          ) : null}

          {error ? (
            <Text style={styles.error} accessibilityRole="alert" testID="add-item-error">
              {error}
            </Text>
          ) : null}
          <View style={styles.buttons}>
            <View style={styles.grow}>
              <Button variant="secondary" label="취소" onPress={close} disabled={busy} />
            </View>
            <View style={styles.grow}>
              <Button label="항목 추가" onPress={submit} disabled={busy} />
            </View>
          </View>
        </Card>
      ) : (
        <Button variant="secondary" label="+ 항목 추가" a11yLabel="체크 항목 추가" onPress={() => setOpen(true)} />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  grow: { flex: 1 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  line: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  buttons: { flexDirection: "row", gap: 10 },
  more: { gap: 12 },
  caption: { ...font.caption, color: colors.textMuted },
  error: { ...font.caption, color: colors.danger, fontWeight: "600" },
});
