import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { listNotices } from "../api";
import { CATEGORY_LABEL, CHIPS, EMPTY_TEXT, HELP_TEXT, filterNotices, noticeDate, noticesErrorMessage, preview, unreadCount } from "../notices";
import { loadReadIds, saveReadIds } from "../readStore";

/**
 * 더보기 > 공지사항: 서비스 공지를 종류 칩으로 걸러 보고, 누르면 같은 화면에서 내용을 연다.
 * 열어 본 공지는 이 폰에 기억해 '새 글' 표시를 지운다.
 * @returns {import("react").ReactElement}
 */
export default function NoticesScreen() {
  const router = useRouter();
  const [rows, setRows] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [chip, setChip] = useState("all");
  const [openId, setOpenId] = useState(null);
  const [readIds, setReadIds] = useState(() => new Set());

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await listNotices();
      setRows(Array.isArray(res?.rows) ? res.rows : []);
    } catch (e) {
      setRows([]);
      setError(noticesErrorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
    loadReadIds().then(setReadIds);
  }, [load]);

  const shown = useMemo(() => filterNotices(rows, chip), [rows, chip]);
  const unread = useMemo(() => unreadCount(rows, readIds), [rows, readIds]);
  const current = openId ? (rows ?? []).find((n) => n.id === openId) : null;

  const open = (id) => {
    setOpenId(id);
    if (readIds.has(id)) return;
    const next = new Set(readIds).add(id);
    setReadIds(next);
    saveReadIds(next);
  };

  const back = () => {
    if (current) setOpenId(null);
    else if (router.canGoBack()) router.back();
    else router.replace("/my");
  };

  if (current) {
    return (
      <Screen title="공지사항" left={<IconButton name="chevron-back" label="목록으로" onPress={back} />}>
        <View style={styles.detail}>
          <Text style={styles.tag}>{CATEGORY_LABEL[current.category] ?? "공지"}</Text>
          <Text style={styles.detailTitle} accessibilityRole="header">{current.title}</Text>
          <Text style={styles.meta}>{noticeDate(current.created_at)} · 가비 운영팀</Text>
          <Text style={styles.body}>{current.body}</Text>
          <Text style={styles.help}>{HELP_TEXT}</Text>
          <Button label="확인했어요" onPress={back} testID="notice-done" />
        </View>
      </Screen>
    );
  }

  const chips = (
    <View style={styles.chips} accessibilityRole="tablist">
      {CHIPS.map((c) => {
        const on = c.key === chip;
        return (
          <Pressable key={c.key} onPress={() => setChip(c.key)} accessibilityRole="tab" accessibilityState={{ selected: on }} style={[styles.chip, on && styles.chipOn]}>
            <Text style={[styles.chipText, on && styles.chipTextOn]}>{c.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );

  return (
    <Screen
      title="공지사항"
      subtitle={rows && rows.length ? `안 읽음 ${unread}` : undefined}
      left={<IconButton name="chevron-back" label="뒤로" onPress={back} />}
      right={<IconButton name="refresh-outline" label="새로고침" onPress={load} />}
      pinned={chips}
    >
      {rows === null ? (
        <ActivityIndicator color={colors.primary} style={styles.loading} />
      ) : error ? (
        <Text style={styles.error} accessibilityRole="alert">{error}</Text>
      ) : shown.length === 0 ? (
        <Text style={styles.empty}>{EMPTY_TEXT}</Text>
      ) : (
        <View style={styles.list}>
          {shown.map((n) => {
            const isNew = !readIds.has(n.id);
            return (
              <Pressable key={n.id} onPress={() => open(n.id)} accessibilityRole="button" accessibilityLabel={`${isNew ? "새 글, " : ""}${n.title}`} style={({ pressed }) => [styles.card, pressed && styles.pressed]} testID={`notice-${n.id}`}>
                <View style={styles.cardTop}>
                  <Text style={styles.tag}>{CATEGORY_LABEL[n.category] ?? "공지"}</Text>
                  {isNew ? (
                    <View style={styles.newRow}>
                      <View style={styles.dot} />
                      <Text style={styles.newText}>새 글</Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.cardTitle}>{n.title}</Text>
                <Text style={styles.preview} numberOfLines={2}>{preview(n.body)}</Text>
                <Text style={styles.meta}>{noticeDate(n.created_at)}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, paddingVertical: spacing.sm },
  chip: { minHeight: 36, paddingHorizontal: spacing.lg, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, justifyContent: "center" },
  chipOn: { backgroundColor: colors.dark, borderColor: colors.dark },
  chipText: { ...font.caption, fontSize: 14, color: colors.text },
  chipTextOn: { color: colors.onDark },
  list: { gap: 10 },
  card: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, borderRadius: radius.card, padding: spacing.lg, gap: spacing.sm },
  pressed: { opacity: 0.7 },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  tag: { alignSelf: "flex-start", ...font.caption, fontSize: 12, color: colors.text, backgroundColor: colors.surfaceStrong, paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.pill, overflow: "hidden" },
  newRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.danger },
  newText: { ...font.caption, fontSize: 12, color: colors.danger },
  cardTitle: { ...font.cardTitle, color: colors.text },
  preview: { ...font.caption, fontSize: 14, color: colors.textSub },
  meta: { ...font.caption, fontSize: 12, color: colors.textMuted },
  detail: { gap: spacing.md },
  detailTitle: { ...font.title, fontSize: 22, lineHeight: 32, color: colors.text },
  body: { ...font.body, color: colors.text, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider },
  help: { ...font.caption, fontSize: 14, color: colors.textSub, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md },
  loading: { marginTop: spacing.xxl },
  error: { ...font.caption, color: colors.danger, marginTop: spacing.lg },
  empty: { ...font.caption, fontSize: 14, color: colors.textSub, textAlign: "center", marginTop: 64 },
});
