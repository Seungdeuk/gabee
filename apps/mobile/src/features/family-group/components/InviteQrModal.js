import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import QRCode from "react-native-qrcode-svg";

import Button from "@/shared/components/Button";
import { colors, font } from "@/theme";

/**
 * 초대 링크 QR. 옆에 있는 가족이 폰 기본 카메라로 찍으면 링크가 열린다.
 * 바깥(어두운 부분)을 누르거나 닫기를 누르면 닫힌다.
 */
export default function InviteQrModal({ visible, link, code, caption, onClose }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="QR 닫기">
        <Pressable style={styles.sheet} onPress={() => {}}>
          <Text style={styles.title}>카메라로 찍으면 바로 참여해요</Text>
          <View style={styles.qr} accessible accessibilityLabel={`초대 QR 코드, 초대 코드 ${code}`}>
            {link ? <QRCode value={link} size={220} color={colors.text} backgroundColor="#FFFFFF" /> : null}
          </View>
          <Text style={styles.code} selectable>
            {code}
          </Text>
          {caption ? <Text style={styles.sub}>{caption}</Text> : null}
          <Button label="닫기" variant="secondary" onPress={onClose} testID="invite-qr-close" />
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center", justifyContent: "center", padding: 24 },
  sheet: { width: "100%", maxWidth: 360, borderRadius: 20, backgroundColor: colors.background, padding: 24, gap: 14, alignItems: "stretch" },
  title: { ...font.title, color: colors.text, textAlign: "center" },
  qr: { alignSelf: "center", padding: 12, borderRadius: 16, backgroundColor: "#FFFFFF" },
  code: { ...font.h1, color: colors.text, letterSpacing: 2, textAlign: "center" },
  sub: { ...font.body, color: colors.textSub, textAlign: "center" },
});
