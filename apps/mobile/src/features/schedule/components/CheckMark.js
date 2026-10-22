import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "@/theme";

import { CHECK_LABEL, KIND, KIND_COLOR } from "../constants";

/**
 * 카드의 체크 표시. 약속은 둥근 모양(확인), 할 일은 네모에 가까운 모양(완료).
 * @param {{ kind: "appointment" | "todo", checked: boolean, onPress?: () => void, disabled?: boolean }} props
 */
export default function CheckMark({ kind, checked, onPress, disabled = false }) {
  const color = KIND_COLOR[kind];
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || !onPress}
      hitSlop={10}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={CHECK_LABEL[kind]}
      style={[
        styles.box,
        kind === KIND.appointment ? styles.round : styles.square,
        { borderColor: color },
        checked && { backgroundColor: color },
      ]}
    >
      {checked ? <Ionicons name="checkmark" size={14} color={colors.onDark} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  box: {
    width: 22,
    height: 22,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
  },
  round: { borderRadius: 11 },
  square: { borderRadius: 6 },
});
