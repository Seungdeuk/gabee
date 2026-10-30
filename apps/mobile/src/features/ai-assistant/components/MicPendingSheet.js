import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

/**
 * 마이크(음성 입력)가 아직 준비되지 않았다는 안내 시트: 아래에서 올라오는 둥근 판에 마이크 아이콘과 짧은 설명을 보여 준다.
 * @param {{ visible: boolean, onClose: () => void }} props
 */
export default function MicPendingSheet({ visible, onClose }) {
  return (
    <Modal visible={visible} transparent animationType="none" statusBarTranslucent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기" />
        <SafeAreaView edges={["bottom"]} style={styles.sheet}>
          <View style={styles.grip} />
          <View style={styles.iconWrap}>
            <Ionicons name="mic-outline" size={30} color={colors.text} />
          </View>
          <Text style={styles.title}>업데이트 대기</Text>
          <Text style={styles.body}>음성 입력은 아직 준비 중이에요.{"\n"}업데이트되면 말로 물어볼 수 있어요.</Text>
          <Pressable onPress={onClose} accessibilityRole="button" style={({ pressed }) => [styles.btn, pressed && styles.btnPressed]}>
            <Text style={styles.btnText}>확인</Text>
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(60,40,20,0.4)" },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 12, gap: 10, alignItems: "center" },
  grip: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: 8 },
  iconWrap: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.surfaceStrong, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "700", color: colors.text, textAlign: "center" },
  body: { fontSize: 14, lineHeight: 21, color: colors.textSub, textAlign: "center" },
  btn: { alignSelf: "stretch", minHeight: 48, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: colors.dark, marginTop: 8 },
  btnPressed: { opacity: 0.85 },
  btnText: { fontSize: 15, fontWeight: "600", color: colors.onDark },
});
