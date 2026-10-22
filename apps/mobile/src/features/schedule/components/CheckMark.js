import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "@/theme";

import { CHECK_LABEL, KIND, KIND_COLOR } from "../constants";

/**
 * 카드의 체크 표시. 약속은 동그라미(확인, 복숭아 바탕 + 갈색 체크), 할 일은 네모(완료, 초록 바탕 + 흰 체크).
 * @param {{ kind: "appointment" | "todo", checked: boolean, onPress?: () => void, disabled?: boolean }} props
 */
export default function CheckMark({ kind, checked, onPress, disabled = false }) {
  const isAppointment = kind === KIND.appointment;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || !onPress}
      hitSlop={12}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={CHECK_LABEL[kind]}
      style={[
        styles.box,
        isAppointment ? styles.round : styles.square,
        checked && { backgroundColor: KIND_COLOR[kind], borderColor: KIND_COLOR[kind] },
      ]}
    >
      {checked ? <Ionicons name="checkmark" size={14} color={isAppointment ? colors.text : colors.onDark} /> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  box: {
    width: 18,
    height: 18,
    borderWidth: 1.5,
    borderColor: colors.textMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  round: { borderRadius: 9 },
  square: { borderRadius: 5 },
});
