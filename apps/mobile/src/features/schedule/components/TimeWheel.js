import { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, radius } from "@/theme";

const ITEM = 44;
const VISIBLE = 5;
const PAD = ITEM * Math.floor(VISIBLE / 2);

const pad = (n) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = Array.from({ length: 12 }, (_, i) => i * 5);

/** 위아래로 밀어 한 칸에 멈추는 한 줄. 눌러서도 고를 수 있다. */
function Column({ labels, selected, onSelect }) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.scrollTo({ y: selected * ITEM, animated: false });
  }, [selected]);
  const settle = (event) => {
    const index = Math.min(Math.max(Math.round(event.nativeEvent.contentOffset.y / ITEM), 0), labels.length - 1);
    // 값이 바뀌어 시계가 스스로 움직인 경우(입력 칸에서 고친 값)는 사용자가 민 게 아니므로 값을 덮어쓰지 않는다.
    if (index !== selected) onSelect(index);
  };
  return (
    <ScrollView
      ref={ref}
      style={styles.column}
      contentContainerStyle={{ paddingVertical: PAD }}
      snapToInterval={ITEM}
      decelerationRate="fast"
      showsVerticalScrollIndicator={false}
      onMomentumScrollEnd={settle}
      onScrollEndDrag={settle}
    >
      {labels.map((label, i) => (
        <Pressable key={label} onPress={() => onSelect(i)} style={styles.item} accessibilityRole="button">
          <Text style={[styles.label, i === selected && styles.labelSelected]}>{label}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

/**
 * 시(0~23) / 분을 돌려 고르는 24시간 시계. 분은 5분 단위로 보이고, 키패드로 정한 5분 단위가 아닌 분은 가장 가까운 칸에 걸쳐 보인다.
 * @param {{ value: string, onChange: (time: string) => void }} props value 는 "HH:mm"
 */
export default function TimeWheel({ value, onChange }) {
  const [hour, minute] = value.split(":").map(Number);
  const minuteIndex = Math.min(Math.round(minute / 5), MINUTES.length - 1);
  return (
    <View style={styles.wheels}>
      <View style={styles.band} pointerEvents="none" />
      <Column labels={HOURS.map(pad)} selected={hour} onSelect={(i) => onChange(`${pad(i)}:${pad(minute)}`)} />
      <Column labels={MINUTES.map(pad)} selected={minuteIndex} onSelect={(i) => onChange(`${pad(hour)}:${pad(MINUTES[i])}`)} />
    </View>
  );
}

const styles = StyleSheet.create({
  wheels: { flexDirection: "row", gap: 6, height: ITEM * VISIBLE },
  band: {
    position: "absolute",
    left: 0,
    right: 0,
    top: PAD,
    height: ITEM,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceStrong,
  },
  column: { flex: 1 },
  item: { height: ITEM, alignItems: "center", justifyContent: "center" },
  label: { fontSize: 17, color: colors.textMuted },
  labelSelected: { fontSize: 22, fontWeight: "700", color: colors.text },
});
