import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, View } from "react-native";

import { colors } from "@/theme";

/**
 * 위·아래 한 칸 이동 화살표 두 개(∧ ∨). 각각 별도 칸이고 칸 사이 간격은 0.
 * 칸 폭은 34(세로 터치 높이는 44), 좌우는 hitSlop 으로 터치 영역을 넓힌다. 아이콘은 18.
 * 꺼진 쪽은 옅게 보이고 눌리지 않는다.
 * @param {{ disabledUp?: boolean, disabledDown?: boolean, onUp: () => void, onDown: () => void, label: string }} props
 */
export default function ArrowPair({ disabledUp = false, disabledDown = false, onUp, onDown, label }) {
  const upColor = disabledUp ? colors.disabled : colors.textMuted;
  const downColor = disabledDown ? colors.disabled : colors.textMuted;
  return (
    <View style={styles.pair}>
      <Pressable
        onPress={onUp}
        disabled={disabledUp}
        hitSlop={{ left: 6, right: 0, top: 0, bottom: 0 }}
        style={styles.cell}
        accessibilityRole="button"
        accessibilityLabel={`${label} 위로 한 칸`}
        accessibilityState={{ disabled: disabledUp }}
      >
        <Ionicons name="chevron-up" size={18} color={upColor} />
      </Pressable>
      <Pressable
        onPress={onDown}
        disabled={disabledDown}
        hitSlop={{ left: 0, right: 6, top: 0, bottom: 0 }}
        style={styles.cell}
        accessibilityRole="button"
        accessibilityLabel={`${label} 아래로 한 칸`}
        accessibilityState={{ disabled: disabledDown }}
      >
        <Ionicons name="chevron-down" size={18} color={downColor} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  pair: { flexDirection: "row", alignItems: "center", gap: 0 },
  cell: { width: 34, height: 44, alignItems: "center", justifyContent: "center" },
});
