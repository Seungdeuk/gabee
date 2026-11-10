import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import BottomSheet from "../../components/BottomSheet";
import { CALL_ITEM_KEYWORD } from "../logic";

/**
 * 통화 뒤 시트: "OO와 통화 잘 하셨나요?"와 "안부 전화" 습관을 오늘 완료로 체크할지 묻는다. 메모 칸은 없다.
 * 부모(DailyCheckScreen)가 shouldShowCallDone 이 true 일 때만 연다.
 * - onDone(): "완료로 체크하기"(복숭아). 안부 전화 습관을 완료로 바꾸고 시트를 닫는다.
 * - onLater(): "다음에 할게요"(텍스트). 아무것도 바꾸지 않고 닫는다.
 * @param {{ visible: boolean, memberName: string, onDone: () => void, onLater: () => void }} props
 */
export default function CallDoneSheet({ visible, memberName, onDone, onLater }) {
  return (
    <BottomSheet visible={visible} onClose={onLater}>
      <View style={styles.icon}>
        <Ionicons name="call-outline" size={26} color={colors.success} />
      </View>
      <Text style={styles.title} accessibilityRole="header">
        {`${memberName}와 통화 잘 하셨나요?`}
      </Text>
      <Text style={styles.sub}>{`‘${CALL_ITEM_KEYWORD}’를 오늘 완료로 체크할까요?`}</Text>

      <View style={styles.row}>
        <Pressable onPress={onLater} style={styles.laterButton} accessibilityRole="button" accessibilityLabel="다음에 할게요">
          <Text style={styles.laterText}>다음에 할게요</Text>
        </Pressable>
        <Pressable onPress={onDone} style={[styles.btn, styles.done]} accessibilityRole="button" accessibilityLabel="완료로 체크하기">
          <Text style={styles.doneText}>완료로 체크하기</Text>
        </Pressable>
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  icon: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.successSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  title: { ...font.title, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  row: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: spacing.sm },
  btn: { flex: 1, minHeight: 56, borderRadius: radius.button, alignItems: "center", justifyContent: "center" },
  // 다음에 할게요: 텍스트 버튼(테두리·바탕 없음)
  laterButton: { minHeight: 56, paddingHorizontal: spacing.md, alignItems: "center", justifyContent: "center" },
  laterText: { fontSize: 16, fontWeight: "500", color: colors.textSub },
  done: { backgroundColor: colors.peach },
  doneText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
