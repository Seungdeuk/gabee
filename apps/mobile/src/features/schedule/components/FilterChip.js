import { useRef } from "react";
import { Pressable, StyleSheet, Text } from "react-native";

import { colors, radius } from "@/theme";

/**
 * 누구·주제 필터 칩. 켜져 있으면 복숭아 바탕(accent 색이 있으면 그 색 바탕 + 흰 글자) + 굵은 글자. 추가 칩("+ 누구")은 옅은 글자. ringed 면 갈색 테두리로 강조한다(길게 눌린 칩).
 * onPressRect/onLongPressRect 는 누른 칩의 화면 좌표({x,y,width,height})를 받는다(말풍선을 그 칩 곁에 띄울 때).
 * @param {{ label: string, selected?: boolean, muted?: boolean, ringed?: boolean, accent?: string, onPress?: () => void, onLongPress?: () => void,
 *   onPressRect?: (rect: { x: number, y: number, width: number, height: number }) => void,
 *   onLongPressRect?: (rect: { x: number, y: number, width: number, height: number }) => void }} props
 */
export default function FilterChip({
  label,
  selected = false,
  muted = false,
  ringed = false,
  accent,
  onPress,
  onLongPress,
  onPressRect,
  onLongPressRect,
}) {
  const ref = useRef(null);
  const withRect = (callback) => () => ref.current?.measureInWindow((x, y, width, height) => callback({ x, y, width, height }));

  return (
    <Pressable
      ref={ref}
      onPress={onPressRect ? withRect(onPressRect) : onPress}
      onLongPress={onLongPressRect ? withRect(onLongPressRect) : onLongPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={[styles.chip, selected && styles.selected, selected && accent && { backgroundColor: accent, borderColor: accent }, ringed && styles.ringed]}
    >
      <Text style={[styles.label, muted && styles.muted, selected && styles.labelSelected, selected && accent && styles.labelAccent]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: 11,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  selected: { backgroundColor: colors.peach, borderColor: colors.peach },
  ringed: { borderColor: colors.text },
  label: { fontSize: 13, fontWeight: "500", color: colors.text },
  muted: { color: colors.textMuted },
  labelSelected: { fontWeight: "700" },
  labelAccent: { color: colors.onDark }, // 주제 색 바탕 위에서는 흰 글자
});
