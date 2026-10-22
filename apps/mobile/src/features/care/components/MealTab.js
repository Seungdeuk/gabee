import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getMealMenu, getMeals } from "../api";

/**
 * 식단 추천: 아침·점심·저녁 중 아직 기록되지 않은 끼니의 메뉴. "다른 메뉴"로 순환한다.
 * @param {{ notify: (text: string, isError?: boolean) => void }} props
 */
export default function MealTab({ notify }) {
  const { data, error, loading } = useResource(getMeals);
  const [override, setOverride] = useState({}); // 끼니 -> "다른 메뉴"로 바꾼 메뉴

  const next = async (meal) => {
    try {
      const current = override[meal.meal] ?? meal;
      const menu = await getMealMenu(meal.meal, current.next_index);
      setOverride((o) => ({ ...o, [meal.meal]: menu }));
    } catch (e) {
      notify(e.message, true);
    }
  };

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "식단을 불러오지 못했어요"}</Text>;
  if (data.meals.length === 0) return <Text style={styles.muted}>모든 끼니가 기록됐어요</Text>;

  return (
    <View style={styles.wrap}>
      <Card tone="blue">
        <Text style={styles.caption}>아직 기록되지 않은 끼니만 보여 줘요.</Text>
      </Card>
      {data.meals.map((m) => {
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
              <Button small variant="secondary" label="다른 메뉴" a11yLabel={`${m.label} 다른 메뉴`} onPress={() => next(m)} />
            </View>
          </Card>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1, gap: 2 },
  menu: { ...font.title, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 16 },
  error: { ...font.body, color: colors.danger },
});
