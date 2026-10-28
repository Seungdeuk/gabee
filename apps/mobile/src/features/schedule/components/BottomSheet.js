import { useEffect, useRef, useState } from "react";
import { Keyboard, Modal, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, spacing } from "@/theme";

/**
 * 아래에서 올라오는 시트(날짜·시간 선택에 씀). 바깥을 누르면 닫힌다.
 * 키보드가 올라오면 키보드가 가리는 만큼 시트를 밀어 올리고, 그래도 안 들어가면 시트 안쪽이 스크롤된다(달력이 키보드에 잘리지 않게).
 * 화면이 키보드 때문에 이미 줄어든 기기에서는 겹치는 만큼만 올리도록 시트 영역의 실제 위치를 재서 계산한다.
 * @param {{ visible: boolean, onClose: () => void, children: import("react").ReactNode }} props
 */
export default function BottomSheet({ visible, onClose, children }) {
  const insets = useSafeAreaInsets();
  const rootRef = useRef(null);
  const [keyboardTop, setKeyboardTop] = useState(null);
  const [lift, setLift] = useState(0);

  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKeyboardTop(e.endCoordinates.screenY));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKeyboardTop(null));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  // 시트 영역의 아래 끝이 키보드 위끝보다 아래로 내려간 만큼이 가려지는 높이다.
  const measure = () => {
    if (keyboardTop === null) {
      setLift(0);
      return;
    }
    rootRef.current?.measureInWindow((x, y, width, height) => setLift(Math.max(0, y + height - keyboardTop)));
  };
  useEffect(measure, [keyboardTop]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View ref={rootRef} style={[styles.root, { paddingBottom: lift }]} onLayout={measure}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기" />
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <ScrollView
            style={styles.scroll}
            contentContainerStyle={[styles.content, { paddingBottom: lift > 0 ? spacing.md : spacing.xl + insets.bottom }]}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
            bounces={false}
          >
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  backdrop: { flex: 1, minHeight: 56, backgroundColor: "rgba(85,59,41,0.35)" },
  sheet: {
    flexShrink: 1,
    backgroundColor: colors.background,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
  },
  scroll: { flexGrow: 0 },
  content: { gap: spacing.sm, paddingTop: spacing.sm },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.disabled,
  },
});
