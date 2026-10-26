import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { EMPTY_LINKS_TEXT, KIND_LABEL, canDeleteLink, filterByKind, formatLinkWhen, isTempLink, linkA11yLabel, linkSourceLine } from "../linkUtils";

const FILTERS = [
  { key: "all", label: "전체" },
  { key: "event", label: "일정" },
  { key: "todo", label: "할 일" },
];
const CONFIRM_MS = 3000; // 삭제 확인 상태를 이 시간 뒤에 풀어 준다

/**
 * 채팅방에서 등록한 일정·할 일 목록 시트(서랍 "가족 일정 · 할 일"). 항목은 종류 배지·제목·날짜·시간·원본 한 줄이고,
 * 누르면 시트를 닫고 원본 메시지로 이동한다(onPick). 내가 만든 항목에만 "삭제"가 있고, 한 번 누르면 "한 번 더"로 바뀌어 다시 누르면 지운다(연결만 지워진다).
 * 일정·할 일 자체를 열거나 고치는 기능은 없다.
 * @param {{ visible: boolean, onClose: () => void, links: object[], status: "loading" | "ready" | "error", myId?: string | null, notice?: string, onPick: (messageId: number) => void, onDelete: (link: object) => void, onRetry: () => void }} props
 */
export default function LinksSheet({ visible, onClose, links, status, myId, notice = "", onPick, onDelete, onRetry }) {
  const [kind, setKind] = useState("all");
  const [confirmId, setConfirmId] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    if (!visible) {
      setConfirmId(null);
      clearTimeout(timer.current);
    }
  }, [visible]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const rows = filterByKind(links, kind);

  const askDelete = (link) => {
    if (confirmId === link.id) {
      clearTimeout(timer.current);
      setConfirmId(null);
      onDelete(link);
      return;
    }
    setConfirmId(link.id);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setConfirmId(null), CONFIRM_MS);
  };

  let body;
  if (status === "loading" && links.length === 0) {
    body = <ActivityIndicator color={colors.accent} style={styles.center} accessibilityLabel="불러오는 중" />;
  } else if (status === "error" && links.length === 0) {
    body = (
      <View style={styles.center}>
        <Text style={styles.error} accessibilityRole="alert">
          목록을 불러오지 못했어요
        </Text>
        <Button label="다시 불러오기" small variant="secondary" onPress={onRetry} />
      </View>
    );
  } else if (rows.length === 0) {
    body = (
      <Text style={styles.empty} testID="chat-links-empty">
        {links.length === 0 ? EMPTY_LINKS_TEXT : `${KIND_LABEL[kind]} 항목이 없어요`}
      </Text>
    );
  } else {
    body = rows.map((link) => {
      const when = formatLinkWhen(link.date, link.time);
      const deletable = canDeleteLink(link, myId);
      return (
        <View key={link.id} style={styles.item}>
          <Pressable
            onPress={() => onPick(link.message_id)}
            accessibilityRole="button"
            accessibilityLabel={linkA11yLabel(link)}
            style={({ pressed }) => [styles.main, pressed && styles.pressed]}
          >
            <View style={styles.titleRow}>
              <Text style={[styles.badge, link.kind === "event" ? styles.badgeEvent : styles.badgeTodo]}>{KIND_LABEL[link.kind]}</Text>
              <Text style={styles.itemTitle} numberOfLines={2}>
                {link.title}
              </Text>
            </View>
            {when ? <Text style={styles.when}>{when}</Text> : null}
            <Text style={styles.source} numberOfLines={1}>
              {isTempLink(link) ? "저장하는 중이에요" : linkSourceLine(link)}
            </Text>
          </Pressable>
          {deletable ? (
            <Pressable
              onPress={() => askDelete(link)}
              accessibilityRole="button"
              accessibilityLabel={confirmId === link.id ? "한 번 더 누르면 연결을 지워요" : "연결 삭제. 일정·할 일은 지워지지 않아요"}
              style={styles.delete}
            >
              <Text style={[styles.deleteText, confirmId === link.id && styles.deleteConfirm]}>{confirmId === link.id ? "한 번 더" : "삭제"}</Text>
            </Pressable>
          ) : null}
        </View>
      );
    });
  }

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.root}>
        <Pressable style={styles.backdrop} onPress={onClose} accessibilityRole="button" accessibilityLabel="일정·할 일 목록 닫기" />
        <View style={styles.sheet} testID="chat-links">
          <View style={styles.handle} />
          <View style={styles.header}>
            <Text style={styles.title} accessibilityRole="header">
              가족 일정 · 할 일
            </Text>
            <Pressable onPress={onClose} hitSlop={spacing.sm} accessibilityRole="button" accessibilityLabel="닫기">
              <Text style={styles.close}>닫기</Text>
            </Pressable>
          </View>
          <View style={styles.filters}>
            {FILTERS.map((f) => (
              <Pressable
                key={f.key}
                onPress={() => setKind(f.key)}
                accessibilityRole="button"
                accessibilityState={{ selected: kind === f.key }}
                style={[styles.chip, kind === f.key && styles.chipOn]}
              >
                <Text style={[styles.chipText, kind === f.key && styles.chipTextOn]}>{f.label}</Text>
              </Pressable>
            ))}
          </View>
          <ScrollView contentContainerStyle={styles.content}>{body}</ScrollView>
          {notice ? (
            <View style={styles.notice} accessibilityLiveRegion="polite">
              <Text style={styles.noticeText}>{notice}</Text>
            </View>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: colors.text, opacity: 0.4 },
  sheet: { maxHeight: "85%", minHeight: "40%", backgroundColor: colors.background, borderTopLeftRadius: radius.card, borderTopRightRadius: radius.card, paddingTop: spacing.sm },
  handle: { alignSelf: "center", width: 40, height: spacing.xs, borderRadius: radius.pill, backgroundColor: colors.disabled },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  title: { ...font.cardTitle, color: colors.text },
  close: { ...font.bodyStrong, color: colors.accent },
  filters: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  chip: { paddingHorizontal: spacing.md, minHeight: 32, justifyContent: "center", borderRadius: radius.pill, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.surfaceStrong },
  chipText: { ...font.caption, color: colors.textSub },
  chipTextOn: { fontFamily: font.bodyStrong.fontFamily, color: colors.text },
  content: { paddingBottom: spacing.xxl },
  center: { alignItems: "center", gap: spacing.md, paddingVertical: spacing.xxl },
  empty: { ...font.body, color: colors.textMuted, textAlign: "center", paddingVertical: spacing.xxl, paddingHorizontal: spacing.lg },
  error: { ...font.body, color: colors.danger },
  item: { flexDirection: "row", alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.divider },
  main: { flex: 1, minWidth: 0, gap: 2, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  pressed: { backgroundColor: colors.surfaceStrong },
  titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  badge: { ...font.tab, fontFamily: font.bodyStrong.fontFamily, paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, overflow: "hidden" },
  badgeEvent: { backgroundColor: colors.honeySoft, color: colors.accent },
  badgeTodo: { backgroundColor: colors.successSoft, color: colors.success },
  itemTitle: { ...font.bodyStrong, color: colors.text, flex: 1 },
  when: { ...font.caption, color: colors.textSub },
  source: { ...font.caption, color: colors.textMuted },
  delete: { minWidth: 56, minHeight: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.sm },
  deleteText: { ...font.caption, color: colors.textMuted },
  deleteConfirm: { color: colors.danger, fontFamily: font.bodyStrong.fontFamily },
  notice: { alignItems: "center", paddingVertical: spacing.sm, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
});
