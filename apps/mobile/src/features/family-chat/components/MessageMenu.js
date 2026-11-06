import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, useWindowDimensions, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { DELETE_BODY, DELETE_TITLE, REACTIONS, menuKeys, menuPosition, myReaction } from "../messageActions";

const MENU_WIDTH = 196; // 말풍선 옆에 작게 붙는 크기
const REACTION_ROW = 40;
const ITEM_HEIGHT = 38;
const CONFIRM_WIDTH = 264;
const CONFIRM_HEIGHT = 156;

const ITEMS = {
  reply: { icon: "arrow-undo-outline", label: "답장" },
  pin: { icon: "pin", label: "공지로 등록" },
  unpin: { icon: "pin-outline", label: "게시판에서 내리기" },
  copy: { icon: "copy-outline", label: "복사" },
  delete: { icon: "trash-outline", label: "삭제", danger: true },
};

/**
 * 메시지를 길게 눌렀을 때 그 메시지 근처에 뜨는 팝업 메뉴(Modal 이라 웹에서도 같다). 맨 위에 반응 이모지 6개(내가 누른 것은 강조), 아래로 답장·공지 등록(또는 게시판에서 내리기)·복사·삭제.
 * 어떤 항목이 열리는지는 messageActions.menuKeys 가 정한다(삭제는 내가 보낸 메시지만, 복사·공지는 글자가 있는 메시지만). 삭제를 누르면 같은 팝업이 "모두에게서 삭제돼요" 확인으로 바뀐다.
 * target 이 없으면 닫힌 상태다. 누른 지점을 모르면(웹 등) 화면 가운데에 뜬다.
 * @param {{ target: { message: object, anchor?: { x: number, y: number } | null } | null, myId?: string | null, pinned: boolean, onClose: () => void, onReact: (emoji: string) => void, onReply: () => void, onPin: () => void, onUnpin: () => void, onCopy: () => void, onDelete: () => void }} props
 */
export default function MessageMenu({ target, myId = null, pinned, onClose, onReact, onReply, onPin, onUnpin, onCopy, onDelete }) {
  const screen = useWindowDimensions();
  const [confirming, setConfirming] = useState(false);
  const message = target?.message ?? null;
  useEffect(() => setConfirming(false), [message?.id]); // 다른 메시지로 열면 확인 단계를 처음으로
  if (!message) return null;

  const keys = menuKeys({ message, myId, pinned });
  const rows = keys.filter((k) => k !== "reactions");
  const height = confirming ? CONFIRM_HEIGHT : (keys.includes("reactions") ? REACTION_ROW : 0) + rows.length * ITEM_HEIGHT;
  const width = confirming ? CONFIRM_WIDTH : MENU_WIDTH;
  const anchor = target.anchor ?? { x: screen.width / 2, y: screen.height / 2 - height / 2 };
  // 삭제 확인은 화면 가운데에, 메뉴는 지정한 말풍선 바로 아래에 띄운다
  const { left, top } = confirming ? { left: (screen.width - width) / 2, top: Math.max(spacing.sm, (screen.height - height) / 2) } : menuPosition(anchor, { width, height }, screen);
  const mine = myReaction(target?.reactTo ?? message); // 앨범의 반응은 앨범 대표 사진(마지막)에 건다
  const handlers = { reply: onReply, pin: onPin, unpin: onUnpin, copy: onCopy, delete: () => setConfirming(true) };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="메뉴 닫기" />
        <View style={[styles.menu, { left, top, width }]} accessibilityViewIsModal>
          {confirming ? (
            <View style={styles.confirm}>
              <Text style={styles.confirmTitle} accessibilityRole="header">
                {DELETE_TITLE}
              </Text>
              <Text style={styles.confirmBody}>{DELETE_BODY}</Text>
              <View style={styles.confirmRow}>
                <Pressable onPress={() => setConfirming(false)} accessibilityRole="button" accessibilityLabel="취소" style={({ pressed }) => [styles.confirmBtn, pressed && styles.pressed]}>
                  <Text style={styles.cancelText}>취소</Text>
                </Pressable>
                <Pressable onPress={onDelete} accessibilityRole="button" accessibilityLabel="삭제" style={({ pressed }) => [styles.confirmBtn, styles.confirmDanger, pressed && styles.pressed]}>
                  <Text style={styles.deleteText}>삭제</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <>
              {keys.includes("reactions") ? (
                <View style={styles.reactions} accessibilityRole="toolbar" accessibilityLabel="반응">
                  {REACTIONS.map((r) => (
                    <Pressable
                      key={r.emoji}
                      onPress={() => onReact(r.emoji)}
                      accessibilityRole="button"
                      accessibilityLabel={mine === r.emoji ? `${r.name} 반응 취소` : `${r.name} 반응`}
                      accessibilityState={{ selected: mine === r.emoji }}
                      style={({ pressed }) => [styles.reaction, mine === r.emoji && styles.reactionOn, pressed && styles.pressed]}
                    >
                      <Text style={styles.emoji}>{r.emoji}</Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
              {rows.map((key, index) => {
                const item = ITEMS[key];
                return (
                  <Pressable
                    key={key}
                    onPress={handlers[key]}
                    accessibilityRole="button"
                    accessibilityLabel={item.label}
                    style={({ pressed }) => [styles.item, (index > 0 || keys.includes("reactions")) && styles.itemLine, pressed && styles.pressed]}
                  >
                    <Ionicons name={item.icon} size={16} color={item.danger ? colors.danger : colors.textSub} />
                    <Text style={[styles.label, item.danger && styles.danger]}>{item.label}</Text>
                  </Pressable>
                );
              })}
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.dark, opacity: 0.2 },
  menu: { position: "absolute", backgroundColor: colors.background, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  reactions: { height: REACTION_ROW, flexDirection: "row", alignItems: "center", justifyContent: "space-around", paddingHorizontal: spacing.xs },
  reaction: { width: 30, height: 30, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  reactionOn: { backgroundColor: colors.honeySoft },
  emoji: { ...font.section }, // 이모지 크기는 theme 토큰을 쓴다
  item: { height: ITEM_HEIGHT, flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.md },
  itemLine: { borderTopWidth: 1, borderTopColor: colors.divider },
  pressed: { backgroundColor: colors.surface },
  label: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  danger: { color: colors.danger },
  confirm: { padding: spacing.lg, gap: spacing.sm },
  confirmTitle: { ...font.cardTitle, color: colors.text },
  confirmBody: { ...font.caption, color: colors.textSub },
  confirmRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  confirmBtn: { flex: 1, minHeight: 44, borderRadius: radius.md, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  confirmDanger: { backgroundColor: colors.danger },
  cancelText: { ...font.bodyStrong, color: colors.text },
  deleteText: { ...font.bodyStrong, color: colors.card },
});
