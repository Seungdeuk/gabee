import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import BottomSheet from "../../components/BottomSheet";
import { FormField, TextBox } from "../../components/FormControls";
import { CALL_ITEM_KEYWORD } from "../logic";

/**
 * 통화 뒤 시트: "통화 잘 하셨나요?" 메모(나만 보는 로컬 값)와 "안부 전화" 완료 체크.
 * onDone(memo) 는 완료 처리 결과 안내 문구를 돌려준다. 빈 문구면 시트가 닫힌 것으로 본다(부모가 visible 을 내린다).
 * onLater(memo) 는 메모만 저장하고 닫는다.
 * @param {{ visible: boolean, memberName: string, initialMemo: string, onDone: (memo: string) => string, onLater: (memo: string) => void }} props
 */
export default function CallDoneSheet({ visible, memberName, initialMemo, onDone, onLater }) {
  const [memo, setMemo] = useState(initialMemo);
  const [notice, setNotice] = useState("");

  // 시트를 열거나 저장된 메모가 늦게 도착하면 메모 칸을 그 값으로 맞춘다.
  useEffect(() => {
    if (!visible) return;
    setMemo(initialMemo);
    setNotice("");
  }, [visible, initialMemo]);

  return (
    <BottomSheet visible={visible} onClose={() => onLater(memo)}>
      <View style={styles.icon}>
        <Ionicons name="call-outline" size={26} color={colors.success} />
      </View>
      <Text style={styles.title} accessibilityRole="header">
        {`${memberName}와 통화 잘 하셨나요?`}
      </Text>
      <Text style={styles.sub}>{`‘${CALL_ITEM_KEYWORD}’를 오늘 완료로 체크할까요?`}</Text>

      <FormField label="통화 메모 (선택)">
        <TextBox value={memo} onChangeText={setMemo} placeholder="무릎이 좀 아프시대요" multiline />
      </FormField>
      <Text style={styles.note}>메모는 나만 볼 수 있어요</Text>

      {notice ? <Text style={styles.notice}>{notice}</Text> : null}
      <View style={styles.row}>
        <Pressable
          onPress={() => onLater(memo)}
          style={[styles.btn, styles.later]}
          accessibilityRole="button"
          accessibilityLabel="다음에 할게요"
        >
          <Text style={styles.laterText}>다음에 할게요</Text>
        </Pressable>
        <Pressable
          onPress={() => {
            const message = onDone(memo);
            if (message) setNotice(message);
          }}
          style={[styles.btn, styles.done]}
          accessibilityRole="button"
          accessibilityLabel="완료로 체크하기"
        >
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
  note: { ...font.caption, color: colors.textMuted },
  notice: { fontSize: 14, color: colors.danger, textAlign: "center" },
  row: { flexDirection: "row", gap: 10, marginTop: spacing.sm },
  btn: { flex: 1, minHeight: 56, borderRadius: radius.button, alignItems: "center", justifyContent: "center" },
  later: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card },
  laterText: { fontSize: 16, fontWeight: "700", color: colors.text },
  done: { backgroundColor: colors.peach },
  doneText: { fontSize: 16, fontWeight: "700", color: colors.text },
});
