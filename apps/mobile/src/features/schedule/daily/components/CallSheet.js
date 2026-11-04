import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import avatarTone from "@/shared/avatarTone";
import { colors, font, radius, spacing } from "@/theme";

import BottomSheet from "../../components/BottomSheet";

/**
 * 전화 확인 시트. 가족 아바타와 제목, 가비의 이야깃거리(규칙 문구)를 보여 주고, "전화 걸기"를 누르면 onCall 을 부른다.
 * 번호는 쓰지 않는다. 부모가 Linking.openURL("tel:") 로 전화 앱 키패드를 연다(실패해도 앱은 계속 동작).
 * @param {{ visible: boolean, onClose: () => void, memberId?: string, memberName: string,
 *   points: { say: string, ask: string }[], onCall: () => void }} props
 */
export default function CallSheet({ visible, onClose, memberId = "", memberName, points, onCall }) {
  const tone = avatarTone(memberId || memberName);
  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <View style={styles.head}>
        <View style={[styles.avatar, tone]}>
          <Text style={[styles.avatarText, { color: tone.color }]}>{memberName.charAt(0)}</Text>
        </View>
        <View style={styles.headText}>
          <Text style={styles.title} accessibilityRole="header">
            {`${memberName}에게 전화할까요?`}
          </Text>
          <Text style={styles.sub}>휴대폰의 전화 앱으로 연결돼요</Text>
        </View>
      </View>

      <View style={styles.box}>
        <View style={styles.boxHead}>
          <Ionicons name="chatbubble-ellipses-outline" size={18} color={colors.accent} />
          <Text style={styles.boxTitle}>가비가 추천하는 이야깃거리</Text>
        </View>
        {points.map((p, i) => (
          <View key={i} style={styles.point}>
            <Text style={styles.say}>{p.say}</Text>
            <Text style={styles.ask}>{p.ask}</Text>
          </View>
        ))}
      </View>

      <View style={styles.row}>
        <Pressable onPress={onClose} style={[styles.btn, styles.cancel]} accessibilityRole="button" accessibilityLabel="취소">
          <Text style={styles.cancelText}>취소</Text>
        </Pressable>
        <Pressable
          onPress={onCall}
          style={[styles.btn, styles.call]}
          accessibilityRole="button"
          accessibilityLabel={`${memberName}에게 전화 걸기`}
        >
          <Ionicons name="call-outline" size={20} color={colors.text} />
          <Text style={styles.callText}>전화 걸기</Text>
        </Pressable>
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  avatarText: { fontSize: 18, fontWeight: "700", color: colors.text },
  headText: { flex: 1, gap: 2 },
  title: { ...font.title, color: colors.text },
  sub: { fontSize: 14, color: colors.textSub },
  box: { borderRadius: radius.button, backgroundColor: colors.surface, padding: spacing.lg, gap: 10 },
  boxHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  boxTitle: { fontSize: 14, fontWeight: "700", color: colors.text },
  point: { gap: 2 },
  say: { fontSize: 15, color: colors.text },
  ask: { ...font.caption, color: colors.textSub },
  row: { flexDirection: "row", gap: 10, marginTop: spacing.sm },
  btn: { flex: 1, minHeight: 56, borderRadius: radius.button, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6 },
  cancel: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  cancelText: { fontSize: 16, fontWeight: "700", color: colors.text },
  call: { backgroundColor: colors.peach },
  callText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
