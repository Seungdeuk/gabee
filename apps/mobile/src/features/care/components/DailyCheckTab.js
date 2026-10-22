import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import SectionTitle from "@/shared/components/SectionTitle";
import Tag from "@/shared/components/Tag";
import TimePicker, { formatTime } from "@/shared/components/TimePicker";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { addItem, deleteItem, getDaily, putEntry } from "../api";

const CONDITIONS = [
  { key: "good", label: "좋음" },
  { key: "normal", label: "보통" },
  { key: "bad", label: "나쁨" },
];
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

function entryText(item) {
  const e = item.entry;
  if (!e) return "기록 없음";
  if (item.mode === "yesno") return e.done ? "예" : "아니오";
  if (item.mode === "number") return `${e.number}${item.unit}`;
  return CONDITIONS.find((c) => c.key === e.condition)?.label ?? "";
}

/**
 * 데일리 체크: 항목별 기록(예/아니오, 수치, 컨디션), 누락 표시, 항목 추가·삭제.
 * 누락은 서버가 예정 시각 + 60분을 기준으로 계산한다. 건강 이상을 뜻하지 않는다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function DailyCheckTab({ notify }) {
  const { data, error, loading, reload } = useResource(getDaily);

  const act = async (run, done) => {
    try {
      await run();
      if (done) notify(done);
      await reload();
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "체크 항목을 불러오지 못했어요"}</Text>;

  const missing = data.items.filter((i) => i.missing).length;
  const done = data.items.filter((i) => i.completed).length;

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <Text style={styles.notice}>누락은 아직 기록되지 않았다는 뜻이에요. 건강에 이상이 있다는 뜻은 아니에요.</Text>
        <View style={styles.stats}>
          <Stat label="기준 시각" value={data.now} />
          <Stat label="완료" value={`${done}/${data.items.length}`} testID="done-count" />
          <Stat label="누락" value={String(missing)} testID="missing-count" />
        </View>
      </Card>

      {data.items.map((item) => (
        <Card key={item.id} tone="white">
          <View style={styles.head}>
            <View style={styles.grow}>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.caption}>
                {formatTime(item.scheduled_time)} 예정{item.target ? ` · 목표 ${item.target}${item.unit}` : ""} · {entryText(item)}
              </Text>
            </View>
            {item.missing ? (
              <Tag label="미기록 · 누락" tone="orange" />
            ) : item.completed ? (
              <Tag label="✓ 완료" tone="green" />
            ) : (
              <Tag label="대기" tone="gray" />
            )}
          </View>
          <ItemInput item={item} act={act} notify={notify} />
          <View style={styles.rowEnd}>
            <Button small variant="ghost" label="삭제" a11yLabel={`${item.name} 삭제`} onPress={() => act(() => deleteItem(item.id), "항목을 삭제했어요")} />
          </View>
        </Card>
      ))}

      <AddItemForm notify={notify} onAdded={reload} />
    </View>
  );
}

function ItemInput({ item, act, notify }) {
  const [value, setValue] = useState(item.entry?.number == null ? "" : String(item.entry.number));

  if (item.mode === "yesno") {
    return (
      <View style={styles.options}>
        <Button small variant="secondary" label="예" a11yLabel={`${item.name} 예`} selected={item.entry?.done === true} onPress={() => act(() => putEntry(item.id, { done: true }))} />
        <Button small variant="secondary" label="아니오" a11yLabel={`${item.name} 아니오`} selected={item.entry?.done === false} onPress={() => act(() => putEntry(item.id, { done: false }))} />
      </View>
    );
  }
  if (item.mode === "condition") {
    return (
      <View style={styles.options}>
        {CONDITIONS.map((c) => (
          <Button key={c.key} small variant="secondary" label={c.label} a11yLabel={`${item.name} ${c.label}`} selected={item.entry?.condition === c.key} onPress={() => act(() => putEntry(item.id, { condition: c.key }))} />
        ))}
      </View>
    );
  }
  const save = () => {
    if (!/^\d+$/.test(value.trim())) return notify("숫자만 입력해 주세요", true);
    act(() => putEntry(item.id, { number: parseInt(value.trim(), 10) }), "저장했어요");
  };
  return (
    <View style={styles.line}>
      <Field style={styles.grow} value={value} onChangeText={setValue} placeholder={`${item.name} (${item.unit})`} keyboardType="numeric" />
      <Button small label="저장" a11yLabel={`${item.name} 저장`} onPress={save} />
    </View>
  );
}

function AddItemForm({ notify, onAdded }) {
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

function Stat({ label, value, testID }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.caption}>{label}</Text>
      <Text style={styles.statValue} testID={testID}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1 },
  name: { ...font.cardTitle, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  notice: { ...font.caption, color: colors.text },
  stats: { flexDirection: "row", justifyContent: "space-between" },
  stat: { flex: 1, alignItems: "center", gap: 4 },
  statValue: { ...font.bodyStrong, fontWeight: "700", color: colors.text },
  options: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  line: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  rowEnd: { flexDirection: "row", justifyContent: "flex-end" },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 8 },
  error: { ...font.body, color: colors.danger },
});
