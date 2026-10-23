import { Ionicons } from "@expo/vector-icons";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { colors } from "@/theme";

const CHOICES = [
  { key: "album", icon: "images-outline", label: "앨범", hint: "사진 고르기" },
  { key: "camera", icon: "camera-outline", label: "카메라", hint: "바로 찍기" },
  { key: "file", icon: "document-text-outline", label: "파일", hint: "PDF · 문서 · 엑셀" },
];

/**
 * 올리기 선택 시트: 아래에서 올라오는 둥근 판에 앨범·카메라·파일을 큼직한 타일로 보여 준다.
 * @param {{ visible: boolean, onClose: () => void, onPick: (key: "album" | "camera" | "file") => void }} props
 */
export default function AttachSheet({ visible, onClose, onPick }) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기" />
        <SafeAreaView edges={["bottom"]} style={styles.sheet}>
          <View style={styles.grip} />
          <Text style={styles.title}>무엇을 올릴까요?</Text>
          <View style={styles.row}>
            {CHOICES.map((c) => (
              <Pressable
                key={c.key}
                onPress={() => onPick(c.key)}
                accessibilityRole="button"
                accessibilityLabel={`${c.label}, ${c.hint}`}
                style={({ pressed }) => [styles.tile, pressed && styles.tilePressed]}
              >
                <View style={styles.iconWrap}>
                  <Ionicons name={c.icon} size={26} color={colors.text} />
                </View>
                <Text style={styles.label}>{c.label}</Text>
                <Text style={styles.hint}>{c.hint}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable onPress={onClose} accessibilityRole="button" style={styles.cancel}>
            <Text style={styles.cancelText}>닫기</Text>
          </Pressable>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(60,40,20,0.4)" },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 12, gap: 14 },
  grip: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border },
  title: { fontSize: 17, fontWeight: "700", color: colors.text, textAlign: "center" },
  row: { flexDirection: "row", gap: 10 },
  tile: { flex: 1, minHeight: 112, borderRadius: 18, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", gap: 4, paddingHorizontal: 6 },
  tilePressed: { backgroundColor: colors.surfaceStrong },
  iconWrap: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.card, alignItems: "center", justifyContent: "center", marginBottom: 2 },
  label: { fontSize: 15, fontWeight: "700", color: colors.text },
  hint: { fontSize: 11, color: colors.textMuted, textAlign: "center" },
  cancel: { minHeight: 46, borderRadius: 23, alignItems: "center", justifyContent: "center" },
  cancelText: { fontSize: 15, color: colors.textSub },
});
