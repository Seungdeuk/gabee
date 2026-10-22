import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet } from "react-native";

import { colors } from "@/theme";

/**
 * 날짜·구역 옆의 작은 복숭아색 + 버튼. 누르면 등록 화면으로 가도록 이후 PR에서 연결한다.
 * @param {{ label: string, onPress?: () => void }} props label 은 화면 읽기용 이름
 */
export default function AddButton({ label, onPress }) {
  return (
    <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={label} style={styles.button}>
      <Ionicons name="add" size={18} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 28,
    height: 28,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.peach,
  },
});
