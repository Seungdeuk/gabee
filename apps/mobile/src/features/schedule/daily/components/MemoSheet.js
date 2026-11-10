import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

import BottomSheet from "../../components/BottomSheet";
import { MEMO_MAX, clipMemo, memoLength, validateMemo } from "../logic";

/**
 * 메모 쓰기 시트(시안 2-1). 한 줄 입력(최대 MEMO_MAX 자, "n / 50"), "메모 내용 공유하기" 체크(기본 꺼짐), [저장] 큰 버튼.
 * 메모가 이미 있을 때만 [메모 지우기]를 보인다. 열 때마다 저장된 메모 값으로 다시 채운다.
 * 저장하면 onSave({ note, noteShared }) 를, 지우면 onClear() 를 부른다(저장·지우기 자체는 화면이 한다).
 * @param {{ visible: boolean, onClose: () => void, itemName: string, subtitle: string, note?: string, shared?: boolean,
 *   onSave: (memo: { note: string, noteShared: boolean }) => void, onClear: () => void }} props
 */
export default function MemoSheet({ visible, onClose, itemName, subtitle, note = "", shared = false, onSave, onClear }) {
  const [text, setText] = useState(note);
  const [sharedOn, setSharedOn] = useState(shared);
  // 시트를 열 때마다 저장된 값으로 되돌린다(닫을 때 쓴 값이 남지 않게)
  useEffect(() => {
    if (!visible) return;
    setText(note);
    setSharedOn(shared);
  }, [visible, note, shared]);

  const valid = validateMemo(text).ok;
  const hasMemo = Boolean(note);

  return (
    <BottomSheet visible={visible} onClose={onClose}>
      <View style={styles.head}>
        <Text style={styles.title} accessibilityRole="header">
          {itemName}
        </Text>
        <Text style={styles.sub}>{subtitle}</Text>
      </View>

      <View style={styles.field}>
        <TextInput
          value={text}
          onChangeText={(v) => setText(clipMemo(v))}
          style={styles.input}
          accessibilityLabel="메모"
          returnKeyType="done"
        />
        <View style={styles.countRow}>
          <Text style={styles.count}>{`${memoLength(text)} / ${MEMO_MAX}`}</Text>
        </View>
      </View>

      <Pressable
        onPress={() => setSharedOn((on) => !on)}
        style={styles.shareRow}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: sharedOn }}
        accessibilityLabel="메모 내용 공유하기"
      >
        <View style={[styles.box, sharedOn && styles.boxOn]}>
          {sharedOn ? <Ionicons name="checkmark" size={16} color={colors.onDark} /> : null}
        </View>
        <View style={styles.shareText}>
          <Text style={styles.shareTitle}>메모 내용 공유하기</Text>
          <Text style={styles.shareSub}>끄면 메모는 나만 봐요</Text>
        </View>
      </Pressable>

      <View style={styles.actions}>
        <Pressable
          onPress={() => valid && onSave({ note: text.trim(), noteShared: sharedOn })}
          disabled={!valid}
          style={[styles.save, !valid && styles.saveOff]}
          accessibilityRole="button"
          accessibilityLabel="메모 저장"
          accessibilityState={{ disabled: !valid }}
        >
          <Text style={styles.saveText}>저장</Text>
        </Pressable>
        {hasMemo ? (
          <Pressable onPress={onClear} style={styles.clear} accessibilityRole="button" accessibilityLabel="메모 지우기">
            <Text style={styles.clearText}>메모 지우기</Text>
          </Pressable>
        ) : null}
      </View>
    </BottomSheet>
  );
}

const styles = StyleSheet.create({
  head: { gap: 4 },
  title: { fontSize: 21, fontWeight: "700", color: colors.text },
  sub: { fontSize: 15, color: colors.textSub },
  field: { gap: 8 },
  input: {
    height: 56,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
    backgroundColor: colors.card,
    paddingHorizontal: 16,
    fontSize: 18,
    color: colors.text,
  },
  countRow: { alignItems: "flex-end" },
  count: { fontSize: 13, color: colors.textSub },
  shareRow: {
    minHeight: 56,
    paddingHorizontal: 14,
    borderRadius: 14,
    backgroundColor: colors.surface,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  // 체크 상자: 꺼짐은 흰 바탕 테두리, 켜짐은 초록 채움에 흰 체크
  box: {
    width: 24,
    height: 24,
    borderRadius: 7,
    borderWidth: 1.5,
    borderColor: colors.textMuted,
    backgroundColor: colors.card,
    alignItems: "center",
    justifyContent: "center",
  },
  boxOn: { backgroundColor: colors.success, borderColor: colors.success },
  shareText: { flex: 1, gap: 0 },
  shareTitle: { fontSize: 15, fontWeight: "700", color: colors.text },
  shareSub: { fontSize: 13, color: colors.textSub },
  actions: { gap: 8, marginTop: spacing.sm },
  // 저장은 큰 복숭아 버튼(시안). 글자가 없으면 흐리게 막는다.
  save: { height: 56, borderRadius: radius.button, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  saveOff: { opacity: 0.45 },
  saveText: { fontSize: 16, fontWeight: "700", color: colors.text },
  clear: { height: 48, borderRadius: radius.button, alignItems: "center", justifyContent: "center" },
  clearText: { fontSize: 15, fontWeight: "500", color: colors.danger },
});
