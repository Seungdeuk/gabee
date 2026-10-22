import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

import Button from "./Button";

const ITEM_H = 40; // 휠 한 칸 높이
const VISIBLE = 5; // 한 번에 보이는 칸 수(가운데 칸이 선택된 값)
const PAD = ITEM_H * Math.floor(VISIBLE / 2);

const pad = (n) => String(n).padStart(2, "0");
const PERIODS = ["오전", "오후"];
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1); // 1~12
const minutesOf = (step) => Array.from({ length: 60 / step }, (_, i) => i * step);

/** @param {string} value "HH:MM"(24시간) @returns {{ pm: boolean, hour: number, minute: number }} 오전/오후, 1~12시, 분 */
function parse(value) {
  const [h, m] = value.split(":").map(Number);
  return { pm: h >= 12, hour: h % 12 || 12, minute: m };
}

/** @returns {string} "HH:MM"(24시간) */
function build(pm, hour, minute) {
  return `${pad((hour % 12) + (pm ? 12 : 0))}:${pad(minute)}`;
}

/** @param {string} value "HH:MM" @returns {string} 예: 오후 12:30 */
export const formatTime = (value) => {
  const { pm, hour, minute } = parse(value);
  return `${pm ? "오후" : "오전"} ${hour}:${pad(minute)}`;
};

/**
 * 시간 선택기(휠). 오전/오후, 시, 분(5분 단위)을 세로로 돌려 가운데 칸에 맞춘다.
 * 칸을 눌러도 선택되고, 값은 항상 올바른 "HH:MM"(24시간)이다.
 * @param {{ label?: string, value: string, onChange: (value: string) => void, minuteStep?: number }} props
 */
export default function TimePicker({ label, value, onChange, minuteStep = 5 }) {
  const [open, setOpen] = useState(false);
  const { pm, hour, minute } = parse(value);
  const minutes = minutesOf(minuteStep);

  return (
    <View style={styles.wrap}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <Pressable
        onPress={() => setOpen(!open)}
        accessibilityRole="button"
        accessibilityLabel={`${label ?? "시각"} 선택`}
        aria-expanded={open}
        style={styles.field}
      >
        <Text style={styles.value} testID="time-value">
          {formatTime(value)}
        </Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
      </Pressable>

      {open ? (
        <View style={styles.panel} testID="time-panel">
          <View style={styles.wheels}>
            <View style={styles.band} pointerEvents="none" />
            <Wheel
              testID="wheel-period"
              items={PERIODS}
              selected={pm ? 1 : 0}
              text={(v) => v}
              a11y={(v) => `시간대 ${v}`}
              onSelect={(i) => onChange(build(i === 1, hour, minute))}
            />
            <Wheel
              testID="wheel-hour"
              items={HOURS}
              selected={hour - 1}
              text={(v) => String(v)}
              a11y={(v) => `시 ${v}`}
              onSelect={(i) => onChange(build(pm, HOURS[i], minute))}
            />
            <Wheel
              testID="wheel-minute"
              items={minutes}
              selected={minutes.indexOf(minute)}
              text={pad}
              a11y={(v) => `분 ${pad(v)}`}
              onSelect={(i) => onChange(build(pm, hour, minutes[i]))}
            />
          </View>
          <Button small label="완료" a11yLabel={`${label ?? "시각"} 선택 완료`} onPress={() => setOpen(false)} />
        </View>
      ) : null}
    </View>
  );
}

/**
 * 세로로 돌리는 한 줄. 스크롤이 멈추면 가운데 칸을 고르고 칸 경계에 맞춘다. 칸을 눌러도 선택된다.
 * @param {{ items: (string | number)[], selected: number, text: (v: any) => string, a11y: (v: any) => string, onSelect: (index: number) => void, testID?: string }} props
 */
function Wheel({ items, selected, text, a11y, onSelect, testID }) {
  const ref = useRef(null);
  const timer = useRef(null);
  const current = useRef(selected);
  current.current = selected;

  const scrollTo = (index, animated) => ref.current?.scrollTo({ y: index * ITEM_H, animated });

  // 바깥에서 값이 바뀌면(처음 열릴 때 포함) 그 칸이 가운데 오도록 맞춘다
  useEffect(() => {
    scrollTo(selected, false);
  }, [selected]);
  useEffect(() => () => clearTimeout(timer.current), []);

  const onScroll = (e) => {
    const y = e.nativeEvent.contentOffset.y;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const index = Math.min(items.length - 1, Math.max(0, Math.round(y / ITEM_H)));
      if (index !== current.current) onSelect(index);
      if (Math.abs(y - index * ITEM_H) > 1) scrollTo(index, true); // 칸 경계로 맞춘다
    }, 90);
  };

  return (
    <ScrollView
      ref={ref}
      testID={testID}
      style={styles.wheel}
      contentContainerStyle={{ paddingVertical: PAD }}
      showsVerticalScrollIndicator={false}
      snapToInterval={ITEM_H}
      decelerationRate="fast"
      scrollEventThrottle={16}
      onScroll={onScroll}
    >
      {items.map((v, i) => (
        <Pressable
          key={String(v)}
          onPress={() => {
            scrollTo(i, true);
            if (i !== current.current) onSelect(i);
          }}
          accessibilityRole="button"
          accessibilityLabel={a11y(v)}
          aria-selected={i === selected}
          style={styles.item}
        >
          <Text style={[styles.itemText, i === selected && styles.itemTextOn]}>{text(v)}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 6 },
  label: { fontSize: 14, fontWeight: "500", color: colors.text },
  field: {
    height: 46,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingHorizontal: 12,
    backgroundColor: colors.card,
  },
  value: { fontSize: 15, color: colors.text },
  panel: { gap: 12, padding: 12, borderRadius: 16, backgroundColor: colors.surface },
  wheels: { flexDirection: "row", justifyContent: "center", gap: 8, height: ITEM_H * VISIBLE },
  band: {
    position: "absolute",
    left: 0,
    right: 0,
    top: PAD,
    height: ITEM_H,
    borderRadius: 12,
    backgroundColor: colors.surfaceStrong,
  },
  wheel: { flexGrow: 0, width: 84, height: ITEM_H * VISIBLE },
  item: { height: ITEM_H, alignItems: "center", justifyContent: "center" },
  itemText: { ...font.body, color: colors.textMuted },
  itemTextOn: { ...font.title, color: colors.text },
});
