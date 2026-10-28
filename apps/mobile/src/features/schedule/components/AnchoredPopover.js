import { useEffect, useRef, useState } from "react";
import { Keyboard, Modal, Pressable, StyleSheet, useWindowDimensions, View } from "react-native";

import { colors, radius } from "@/theme";

import { popoverPosition } from "../popover";

/**
 * 칩 테두리에 딱 붙어(위/아래/오른쪽) 뜨는 말풍선. 투명 Modal 안에 윈도우 좌표(칩의 measureInWindow)로 놓아서 부모 영역에 잘리지 않고 터치도 받는다.
 * 바깥(배경)을 누르면 onClose, autoCloseMs 가 있으면 그 시간 뒤에 저절로 닫힌다. 키보드가 올라오면 키보드 위로 올라간다.
 * @param {{ anchor: { x: number, y: number, width: number, height: number } | null, visible: boolean, onClose: () => void,
 *   width: number, placement?: "above" | "below" | "right", tone?: "light" | "dark", autoCloseMs?: number, children: import("react").ReactNode }} props
 */
export default function AnchoredPopover({
  anchor,
  visible,
  onClose,
  width,
  placement = "below",
  tone = "light",
  autoCloseMs,
  children,
}) {
  const screen = useWindowDimensions();
  const [height, setHeight] = useState(0);
  const [keyboardTop, setKeyboardTop] = useState(null);
  const rootRef = useRef(null);
  const [origin, setOrigin] = useState(null);
  const dark = tone === "dark";

  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKeyboardTop(e.endCoordinates.screenY));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKeyboardTop(null));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  useEffect(() => {
    if (!visible || !autoCloseMs) return undefined;
    const timer = setTimeout(onClose, autoCloseMs);
    return () => clearTimeout(timer);
  }, [visible, autoCloseMs, onClose]);

  // 칩 좌표(measureInWindow)와 이 Modal 안의 좌표 원점이 다른 기기(상태 표시줄 높이만큼 어긋남)를 위해 Modal 루트의 원점을 재서 빼 준다.
  const measureOrigin = () =>
    rootRef.current?.measureInWindow((x, y) => setOrigin((prev) => (prev && prev.x === x && prev.y === y ? prev : { x, y })));

  if (!visible || !anchor) return null;

  const pos = popoverPosition({
    anchor,
    width,
    height,
    screenWidth: screen.width,
    screenHeight: screen.height,
    placement,
    keyboardTop,
  });

  return (
    <Modal transparent visible animationType="none" statusBarTranslucent onRequestClose={onClose}>
      <View ref={rootRef} collapsable={false} style={StyleSheet.absoluteFill} onLayout={measureOrigin}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="닫기" />
        <View
          pointerEvents="box-none"
          onLayout={(e) => setHeight(e.nativeEvent.layout.height)}
          style={[
            styles.box,
            dark ? styles.dark : styles.light,
            { left: pos.left - (origin?.x ?? 0), top: pos.top - (origin?.y ?? 0), width, opacity: height === 0 || origin === null ? 0 : 1 },
          ]}
        >
          {children}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  box: {
    position: "absolute",
    borderRadius: radius.button,
    shadowColor: colors.text,
    shadowOpacity: 0.16,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  light: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  dark: { backgroundColor: colors.text },
});
