import { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import Field from "@/shared/components/Field";
import SectionTitle from "@/shared/components/SectionTitle";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { deleteMealLog, getMealLog, getMealLogSummary, putMealLog } from "../api";
import HoldToDelete from "./HoldToDelete";

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
  const loadSummary = useCallback(() => getMealLogSummary(7), []);
  const summary = useResource(loadSummary, refreshKey);
  const [meal, setMeal] = useState("lunch");
  const [menu, setMenu] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false); // 식단 기록 양식은 "+ 식단 기록"을 눌렀을 때만 보인다
  const [formError, setFormError] = useState(null);

  /** 실행하고 성공 여부를 돌려준다. 실패 문구는 onError 가 있으면 거기로(양식 안), 없으면 화면 위 알림으로 보낸다. */
  const run = async (fn, done, after, onError) => {
    setBusy(true);
    try {
      await fn();
      notify(done);
      after?.();
      await Promise.all([reload(), summary.reload()]);
      onChanged?.();
      return true;
    } catch (e) {
      if (onError) onError(e.message);
      else notify(e.message, true);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const closeForm = () => {
    setOpen(false);
    setMenu("");
    setNote("");
    setFormError(null);
  };

  const frequent = summary.data?.frequent.find((f) => f.meal === meal)?.menus ?? [];

  const save = () => {
    if (!menu.trim()) return setFormError("먹은 메뉴를 입력해 주세요");
    setFormError(null);
    // 성공하면 양식을 접고, 실패하면 양식은 그대로 두고 오류를 양식 안에 보여 준다
    run(() => putMealLog({ meal, menu: menu.trim(), note: note.trim(), source: "typed" }), "식단을 기록했어요", closeForm, setFormError);
  };

  return (
    <View style={styles.wrap} testID="meal-log">
      <SectionTitle title="식단 기록" />
      {summary.data ? (
        <Card tone="blue" testID="meal-summary">
          <Text style={styles.body}>
            최근 {summary.data.days}일 {summary.data.logged}/{summary.data.total}끼 기록
          </Text>
          <Text style={styles.caption}>
            {summary.data.per_meal.map((c) => `${c.label} ${c.logged}/${summary.data.days}`).join(" · ")}
          </Text>
        </Card>
      ) : null}
      {open ? (
      <Card tone="white">
        <Text style={styles.label}>끼니</Text>
        <View style={styles.chips}>
          {MEALS.map((m) => (
            <Button key={m.key} small variant="secondary" selected={meal === m.key} label={m.label} a11yLabel={`기록할 끼니 ${m.label}`} onPress={() => setMeal(m.key)} />
          ))}
        </View>
        {frequent.length > 0 ? (
          <View style={styles.chips} testID="frequent-menus">
            <Text style={styles.caption}>자주 먹은 메뉴</Text>
            {frequent.map((f) => (
              <Button key={f.menu} small variant="secondary" label={`${f.menu} · ${f.count}회`} a11yLabel={`자주 먹은 메뉴 ${f.menu}`} onPress={() => setMenu(f.menu)} />
            ))}
          </View>
        ) : null}
        <Field label="먹은 메뉴" value={menu} onChangeText={setMenu} placeholder="예: 닭죽과 김치" />
        <Field label="메모 (선택)" value={note} onChangeText={setNote} placeholder="예: 소금 적게" />
        {formError ? (
          <Text style={styles.error} accessibilityRole="alert" testID="meal-log-error">
            {formError}
          </Text>
        ) : null}
        <View style={styles.buttons}>
          <View style={styles.grow}>
            <Button variant="secondary" label="취소" onPress={closeForm} disabled={busy} />
          </View>
          <View style={styles.grow}>
            <Button label="식단 기록" a11yLabel="식단 기록 저장" onPress={save} disabled={busy} />
          </View>
        </View>
        <Text style={styles.caption}>같은 날 같은 끼니는 새로 적으면 바뀌어요. 기록하면 데일리 체크의 그 끼니도 완료가 돼요.</Text>
      </Card>
      ) : (
        <Button label="+ 식단 기록" a11yLabel="식단 기록 열기" onPress={() => setOpen(true)} />
      )}
      <Text style={styles.caption}>기록한 식단을 길게 누르면 지울 수 있어요.</Text>

      {data?.days.map((d) => (
        <Card key={d.date} tone="white" testID={`log-day-${d.date}`}>
          <Text style={styles.day}>{dayLabel(d.date)}</Text>
          {d.slots.map((s) => (
            <HoldToDelete
              key={s.meal}
              label={`${dayLabel(d.date)} ${s.label} 기록 지우기`}
              disabled={!s.log || busy}
              onDelete={() => run(() => deleteMealLog(d.date, s.meal), "식단 기록을 지웠어요")}
            >
              <View style={styles.row}>
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
              </View>
            </HoldToDelete>
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
  row: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  grow: { flex: 1, gap: 2 },
  buttons: { flexDirection: "row", gap: 10 },
  error: { ...font.caption, color: colors.danger, fontWeight: "600" },
  body: { ...font.body, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
