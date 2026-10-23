import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import SectionTitle from "@/shared/components/SectionTitle";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { deleteMealLog, getMealLog, putMealLog } from "../api";

const MEALS = [
  { key: "breakfast", label: "아침" },
  { key: "lunch", label: "점심" },
  { key: "dinner", label: "저녁" },
];

/** @param {string} iso YYYY-MM-DD @returns {string} 예: 10-23(금) */
function dayLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const week = "일월화수목금토"[new Date(y, m - 1, d).getDay()];
  return `${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}(${week})`;
}

/**
 * 식단 기록: 끼니를 고르고 먹은 메뉴를 적으면 저장하고(같은 끼니는 덮어씀), 최근 7일 기록을 날짜별로 보여 준다.
 * 기록하면 그 끼니의 데일리 체크도 완료가 된다. 사진·영양 정보는 다루지 않는다.
 * @param {{ refreshKey: number, notify: (text: string, isError?: boolean) => void, onChanged: () => void }} props
 */
export default function MealLog({ refreshKey, notify, onChanged }) {
  const load = useCallback(() => getMealLog(7), []);
  const { data, reload } = useResource(load, refreshKey);
  const [meal, setMeal] = useState("lunch");
  const [menu, setMenu] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (fn, done, after) => {
    setBusy(true);
    try {
      await fn();
      notify(done);
      after?.();
      await reload();
      onChanged?.();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!menu.trim()) return notify("먹은 메뉴를 입력해 주세요", true);
    run(
      () => putMealLog({ meal, menu: menu.trim(), note: note.trim(), source: "typed" }),
      "식단을 기록했어요",
      () => {
        setMenu("");
        setNote("");
      },
    );
  };

  return (
    <View style={styles.wrap} testID="meal-log">
      <SectionTitle title="식단 기록" />
      <Card tone="white">
        <Text style={styles.label}>끼니</Text>
        <View style={styles.chips}>
          {MEALS.map((m) => (
            <Button key={m.key} small variant="secondary" selected={meal === m.key} label={m.label} a11yLabel={`기록할 끼니 ${m.label}`} onPress={() => setMeal(m.key)} />
          ))}
        </View>
        <Field label="먹은 메뉴" value={menu} onChangeText={setMenu} placeholder="예: 닭죽과 김치" />
        <Field label="메모 (선택)" value={note} onChangeText={setNote} placeholder="예: 소금 적게" />
        <Button label="식단 기록" a11yLabel="식단 기록 저장" onPress={save} disabled={busy} />
        <Text style={styles.caption}>같은 날 같은 끼니는 새로 적으면 바뀌어요. 기록하면 데일리 체크의 그 끼니도 완료가 돼요.</Text>
      </Card>

      {data?.days.map((d) => (
        <Card key={d.date} tone="white" testID={`log-day-${d.date}`}>
          <Text style={styles.day}>{dayLabel(d.date)}</Text>
          {d.slots.map((s) => (
            <View key={s.meal} style={styles.row}>
              <View style={styles.grow}>
                <Text style={styles.body} testID={`log-${d.date}-${s.meal}`}>
                  {s.label} · {s.log ? s.log.menu : "기록 없음"}
                </Text>
                {s.log ? (
                  <Text style={styles.caption}>
                    {s.log.recorded_by_name} 기록{s.log.source === "recommended" ? " · 추천 메뉴" : ""}
                    {s.log.note ? ` · ${s.log.note}` : ""}
                  </Text>
                ) : null}
              </View>
              {s.log ? (
                <Button small variant="ghost" label="지우기" a11yLabel={`${dayLabel(d.date)} ${s.label} 기록 지우기`} onPress={() => run(() => deleteMealLog(d.date, s.meal), "식단 기록을 지웠어요")} disabled={busy} />
              ) : null}
            </View>
          ))}
        </Card>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  day: { ...font.cardTitle, color: colors.text },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  grow: { flex: 1, gap: 2 },
  body: { ...font.body, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
