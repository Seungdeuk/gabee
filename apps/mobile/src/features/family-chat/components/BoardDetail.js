import { useEffect, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

import { boardAuthor, boardMeta, canOpenOriginal } from "../boardUtils";

/**
 * 게시판 글의 전체 내용. "채팅에서 보기"(원본이 남아 있을 때)와 "삭제"(구성원 누구나, 한 번 더 확인)가 있다.
 * @param {{ item: object | null, nameOf?: (userId: string) => string | undefined, busy?: boolean, notice?: string, onClose: () => void, onOpenOriginal: (item: object) => void, onDelete: (item: object) => void }} props item 이 null 이면 닫혀 있다
 */
export default function BoardDetail({ item, nameOf, busy = false, notice = "", onClose, onOpenOriginal, onDelete }) {
  const [confirming, setConfirming] = useState(false);
  const id = item?.id ?? null;
  useEffect(() => setConfirming(false), [id]); // 다른 글을 열면 확인 단계는 처음으로
  if (!item) return null;
  const author = boardAuthor(item, nameOf);
  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={styles.backdrop} onPress={onClose} accessibilityLabel="닫기" />
      <View style={styles.sheetWrap} pointerEvents="box-none">
        <View style={styles.sheet} accessibilityViewIsModal>
          <View style={styles.tags}>
            {item.is_current ? <Tag label="현재 공지" tone="orange" /> : <Tag label="지난 공지" />}
            {item.message_deleted ? <Tag label="원본 삭제됨" tone="red" /> : null}
          </View>
          <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollBody}>
            <Text style={styles.text} selectable>
              {item.text}
            </Text>
          </ScrollView>
          <Text style={styles.meta}>{boardMeta(item, nameOf)}</Text>
          {author ? <Text style={styles.meta}>{author}</Text> : null}
          {notice ? (
            <Text style={styles.notice} accessibilityLiveRegion="polite">
              {notice}
            </Text>
          ) : null}
          {confirming ? (
            <View style={styles.confirm}>
              <Text style={styles.confirmText}>게시판에서 삭제할까요? 가족 모두의 게시판에서 사라지고 되돌릴 수 없어요.{item.is_current ? " 채팅방 위 공지에서도 내려가요." : ""}</Text>
              <View style={styles.actions}>
                <Button label="취소" variant="secondary" small onPress={() => setConfirming(false)} disabled={busy} />
                <Button label={busy ? "삭제 중" : "삭제"} small onPress={() => onDelete(item)} disabled={busy} />
              </View>
            </View>
          ) : (
            <View style={styles.actions}>
              {canOpenOriginal(item) ? <Button label="채팅에서 보기" small onPress={() => onOpenOriginal(item)} /> : null}
              <Button label="삭제" variant="secondary" small onPress={() => setConfirming(true)} />
              <Button label="닫기" variant="ghost" small onPress={onClose} />
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(85,59,41,0.35)" },
  sheetWrap: { flex: 1, justifyContent: "center", alignItems: "center", padding: spacing.lg },
  sheet: { width: "100%", maxWidth: 520, maxHeight: "80%", backgroundColor: colors.card, borderRadius: radius.card, padding: spacing.lg, gap: spacing.sm },
  tags: { flexDirection: "row", gap: spacing.xs },
  scroll: { flexGrow: 0 },
  scrollBody: { paddingVertical: spacing.xs },
  text: { ...font.body, color: colors.text },
  meta: { ...font.caption, color: colors.textMuted },
  notice: { ...font.caption, color: colors.danger },
  confirm: { gap: spacing.sm },
  confirmText: { ...font.caption, color: colors.text },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, justifyContent: "flex-end" },
});
