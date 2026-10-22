import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "@/theme";

import { CHECK_LABEL, KIND, KIND_COLOR } from "../constants";

/**
 * 카드의 체크 표시. 약속은 동그라미(확인, 복숭아 바탕 + 갈색 체크), 할 일은 네모(완료, 초록 바탕 + 흰 체크).
 * @param {{ kind: "appointment" | "todo", checked: boolean, onPress?: () => void, disabled?: boolean, size?: number }} props
 */
export default function CheckMark({ kind, checked, onPress, disabled = false, size = 18 }) {
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
        { width: size, height: size, borderRadius: isAppointment ? size / 2 : size * 0.28 },
        checked && { backgroundColor: KIND_COLOR[kind], borderColor: KIND_COLOR[kind] },
      ]}
    >
      {checked ? (
        <Ionicons name="checkmark" size={size - 4} color={isAppointment ? colors.text : colors.onDark} />
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  box: {
    borderWidth: 1.5,
    borderColor: colors.textMuted,
    alignItems: "center",
    justifyContent: "center",
  },
});
