import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getMealMenu, getMeals, putMealLog } from "../api";
import MealLog from "./MealLog";

/**
 * 식단: 아직 기록되지 않은 끼니의 추천 메뉴("다른 메뉴"로 순환, "이걸로 먹었어요"로 바로 기록)와 식단 기록.
 * @param {{ notify: (text: string, isError?: boolean) => void, onChanged: () => void }} props onChanged: 기록하면 데일리 체크를 다시 불러온다
 */
export default function MealTab({ notify, onChanged }) {
  const { data, error, loading, reload } = useResource(getMeals);
  const [override, setOverride] = useState({}); // 끼니 -> "다른 메뉴"로 바꾼 메뉴
  const [logKey, setLogKey] = useState(0); // 바뀌면 식단 기록 목록을 다시 불러온다

  const next = async (meal) => {
    try {
      const current = override[meal.meal] ?? meal;
      const menu = await getMealMenu(meal.meal, current.next_index);
      setOverride((o) => ({ ...o, [meal.meal]: menu }));
    } catch (e) {
      notify(e.message, true);
    }
  };

  const ate = async (meal, cur) => {
    try {
      await putMealLog({ meal: meal.meal, menu: cur.menu, source: "recommended" });
      notify(`${meal.label} 식단을 기록했어요`);
      setLogKey((k) => k + 1);
      await reload();
      onChanged?.();
    } catch (e) {
      notify(e.message, true);
    }
  };

  const changed = () => {
    reload();
    onChanged?.();
  };

  return (
    <View style={styles.wrap}>
      {loading && !data ? <Text style={styles.muted}>불러오는 중…</Text> : null}
      {!data && !loading ? <Text style={styles.error}>{error || "식단을 불러오지 못했어요"}</Text> : null}
      {data && data.meals.length === 0 ? <Text style={styles.muted}>모든 끼니가 기록됐어요</Text> : null}
      {data && data.meals.length > 0 ? (
        <Card tone="blue">
          <Text style={styles.caption}>아직 기록되지 않은 끼니만 보여 줘요.</Text>
        </Card>
      ) : null}
      {data?.meals.map((m) => {
        const cur = override[m.meal] ?? m;
        return (
          <Card key={m.meal} tone="white">
            <View style={styles.head}>
              <View style={styles.grow}>
                <Text style={styles.caption}>{m.label}</Text>
                <Text style={styles.menu} testID={`menu-${m.meal}`}>
                  {cur.menu}
                </Text>
                <Text style={styles.caption}>
                  {cur.index + 1} / {cur.total}
                </Text>
              </View>
              <View style={styles.actions}>
                <Button small variant="secondary" label="다른 메뉴" a11yLabel={`${m.label} 다른 메뉴`} onPress={() => next(m)} />
                <Button small label="이걸로 먹었어요" a11yLabel={`${m.label} ${cur.menu} 먹었어요`} onPress={() => ate(m, cur)} />
              </View>
            </View>
          </Card>
        );
      })}
      <MealLog refreshKey={logKey} notify={notify} onChanged={changed} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { gap: 12 },
  grow: { gap: 2 },
  actions: { flexDirection: "row", gap: 8 },
  menu: { ...font.title, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 16 },
  error: { ...font.body, color: colors.danger },
});
