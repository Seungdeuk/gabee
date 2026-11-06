import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import { listNotices } from "../api";
import { CATEGORY_LABEL, EMPTY_TEXT, HELP_TEXT, clampPage, noticeDate, noticesErrorMessage, pageCount, pageSlice, pageWindow, preview, unreadCount } from "../notices";
import { loadReadIds, saveReadIds } from "../readStore";

/**
 * 더보기 > 공지사항: 서비스 공지를 최근순 목록으로 보고(10개를 넘으면 쪽으로 나눈다), 누르면 같은 화면에서 내용을 연다.
 * 열어 본 공지는 이 폰에 기억해 '새 글' 표시를 지운다.
 * @returns {import("react").ReactElement}
 */
export default function NoticesScreen() {
  const router = useRouter();
  const [rows, setRows] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [page, setPage] = useState(0); // 0부터
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

  const pages = pageCount(rows?.length);
  const view = clampPage(page, rows?.length); // 새로고침으로 목록이 줄어도 범위를 벗어난 쪽을 보이지 않는다
  const shown = useMemo(() => pageSlice(rows, view), [rows, view]);
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

  return (
    <Screen
      title="공지사항"
      subtitle={rows && rows.length ? `안 읽음 ${unread}` : undefined}
      left={<IconButton name="chevron-back" label="뒤로" onPress={back} />}
      right={<IconButton name="refresh-outline" label="새로고침" onPress={load} />}
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
          {pages > 1 ? (
            <View style={styles.pager} accessibilityRole="toolbar">
              <Pressable onPress={() => setPage(Math.max(0, view - 1))} disabled={view === 0} accessibilityRole="button" accessibilityLabel="이전 쪽" accessibilityState={{ disabled: view === 0 }} style={styles.pageArrow}>
                <Text style={[styles.pageArrowText, view === 0 && styles.pageOff]}>{"<"}</Text>
              </Pressable>
              {pageWindow(view, pages).map((n) => (
                <Pressable key={n} onPress={() => setPage(n)} accessibilityRole="button" accessibilityLabel={`${n + 1}쪽`} accessibilityState={{ selected: n === view }} style={[styles.pageNo, n === view && styles.pageNoOn]}>
                  <Text style={[styles.pageNoText, n === view && styles.pageNoTextOn]}>{n + 1}</Text>
                </Pressable>
              ))}
              <Pressable onPress={() => setPage(Math.min(pages - 1, view + 1))} disabled={view >= pages - 1} accessibilityRole="button" accessibilityLabel="다음 쪽" accessibilityState={{ disabled: view >= pages - 1 }} style={styles.pageArrow}>
                <Text style={[styles.pageArrowText, view >= pages - 1 && styles.pageOff]}>{">"}</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  pager: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.xs, paddingTop: spacing.md },
  pageArrow: { minWidth: 36, minHeight: 36, alignItems: "center", justifyContent: "center" },
  pageArrowText: { ...font.cardTitle, color: colors.text },
  pageOff: { color: colors.disabled },
  pageNo: { minWidth: 36, minHeight: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center" },
  pageNoOn: { backgroundColor: colors.dark },
  pageNoText: { ...font.caption, fontSize: 14, color: colors.text },
  pageNoTextOn: { color: colors.onDark },
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
