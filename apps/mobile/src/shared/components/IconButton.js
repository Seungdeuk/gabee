import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "@/theme";

/**
 * 44x44 아이콘 버튼.
 * @param {{ name: string, onPress?: () => void, color?: string, size?: number, label?: string }} props
 */
export default function IconButton({ name, onPress, color = colors.text, size = 24, label }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.button, pressed && styles.pressed]}
    >
      <Ionicons name={name} size={size} color={color} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
  },
  pressed: {
    backgroundColor: colors.surfaceStrong,
  },
});
