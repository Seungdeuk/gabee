import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

const AUTO_HIDE_MS = 6000;

/**
 * 길게 눌렀을 때만 작은 삭제 버튼이 나타나는 영역. 평소에는 버튼이 보이지 않고, 6초가 지나거나 영역을 한 번 누르거나 "닫기"를 누르면 다시 숨는다.
 * 화면 낭독기(스크린 리더) 사용자는 길게 누르는 대신 접근성 동작 "삭제"를 쓸 수 있다.
 * 안에 있는 버튼은 평소대로 눌린다.
 * @param {{ label: string, onDelete: () => void, children: import("react").ReactNode, disabled?: boolean, style?: object }} props label 은 삭제 버튼의 접근성 이름(예: "아침 식사 삭제")
 */
export default function HoldToDelete({ label, onDelete, children, disabled = false, style }) {
  const [shown, setShown] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const hide = () => {
    clearTimeout(timer.current);
    setShown(false);
  };
  const reveal = () => {
    if (disabled) return;
    setShown(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setShown(false), AUTO_HIDE_MS);
  };
  const remove = () => {
    hide();
    onDelete();
  };

  return (
    <Pressable
      onLongPress={reveal}
      delayLongPress={400}
      onPress={shown ? hide : undefined}
      accessibilityActions={[{ name: "delete", label }]}
      onAccessibilityAction={(e) => {
        if (e.nativeEvent.actionName === "delete" && !disabled) onDelete();
      }}
      accessibilityHint="길게 누르면 삭제 버튼이 나와요"
      style={style}
    >
      {children}
      {shown ? (
        <View style={styles.actions} testID="hold-delete-actions">
          <Pressable onPress={remove} accessibilityRole="button" accessibilityLabel={label} style={[styles.chip, styles.danger]}>
            <Text style={[styles.chipText, styles.dangerText]}>삭제</Text>
          </Pressable>
          <Pressable onPress={hide} accessibilityRole="button" accessibilityLabel="닫기" style={styles.chip}>
            <Text style={styles.chipText}>닫기</Text>
          </Pressable>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: 6, paddingTop: 6 },
  chip: { height: 28, paddingHorizontal: 10, borderRadius: 8, alignItems: "center", justifyContent: "center", backgroundColor: colors.honeySoft },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  danger: { backgroundColor: colors.dangerSoft },
  dangerText: { color: colors.danger },
});
