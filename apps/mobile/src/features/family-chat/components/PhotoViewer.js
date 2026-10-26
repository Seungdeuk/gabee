import { Modal, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import IconButton from "@/shared/components/IconButton";
import { colors, spacing } from "@/theme";

/**
 * 사진 전체 화면 보기. 원본(attachment.url)을 화면 안에 비율대로 맞춰 보여 주고, 닫기 버튼(또는 뒤로 가기)으로 닫는다.
 * @param {{ path: string, visible: boolean, onClose: () => void }} props path 는 서버가 준 attachment.url
 */
export default function PhotoViewer({ path, visible, onClose }) {
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <SafeAreaView style={styles.safe}>
        <View style={styles.bar}>
          <IconButton name="close" label="사진 닫기" onPress={onClose} color={colors.onDark} />
        </View>
        <AuthImage path={path} contentFit="contain" style={styles.image} accessibilityLabel="사진" />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.dark },
  bar: { alignItems: "flex-end", paddingHorizontal: spacing.sm },
  image: { flex: 1, backgroundColor: colors.dark },
});
