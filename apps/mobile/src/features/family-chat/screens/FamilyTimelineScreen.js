import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { excludePhotoFromTimeline } from "../api";
import PhotoViewer from "../components/PhotoViewer";
import { focusRoute } from "../searchUtils";
import {
  EXCLUDE_LABEL,
  EXCLUDING_LABEL,
  ORIGINAL_LABEL,
  TIMELINE_COLUMNS,
  TIMELINE_EMPTY,
  TIMELINE_EMPTY_HINT,
  TIMELINE_TITLE,
  buildTimelineRows,
  canExclude,
  photoCaption,
  runExclude,
  timelineBodyKind,
} from "../timeline";
import useFamilyTimeline from "../useFamilyTimeline";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 격자가 지나치게 커지지 않게 한다
const GAP = 2;
const NOTICE_MS = 3000;

/**
 * 가족 타임라인: 가족 전체방에 올린 사진 중 일반 사진으로 확인된 것만 촬영일(없으면 보낸 날) 최신순으로 연·월·날짜별로 모아 보인다.
 * 어떤 사진이 나오는지는 서버가 정한다(앱이 더하거나 숨기지 않는다). 사진을 누르면 크게 보고, "원본 메시지로 가기"로 채팅의 그 메시지로 간다.
 * 내가 올린 사진은 "타임라인에서 빼기"로 뺄 수 있다(채팅 원본은 그대로). 조회 실패는 빈 타임라인이 아니라 오류와 "다시 시도"로 보인다.
 */
export default function FamilyTimelineScreen() {
  const router = useRouter();
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const list = useFamilyTimeline();
  const [selected, setSelected] = useState(null);
  const [busyId, setBusyId] = useState(null); // 빼는 중인 사진 id(한 번에 한 장만)
  const [msgs, setMsgs] = useState({}); // 사진 id 별 뷰어 안 오류 문구(다른 사진의 결과가 지금 보는 사진의 문구를 지우지 않는다)
  const [notice, setNotice] = useState(""); // 화면 위 결과 안내(뷰어를 닫은 뒤에도 보인다)
  const working = useRef(new Set()); // 처리 중인 사진 id: 상태가 반영되기 전에 두 번 눌러도 한 번만 보낸다
  const mounted = useRef(true);
  const selectedId = selected?.attachment_id ?? null;

  useEffect(() => {
    mounted.current = true; // 개발 중 Fast Refresh·StrictMode 로 효과가 다시 돌아도 false 로 굳지 않게 한다
    return () => {
      mounted.current = false;
    };
  }, []);

  const kind = timelineBodyKind(list);
  const { loadMore, loadingMore } = list;
  useEffect(() => {
    if (kind === "more" && !loadingMore) loadMore(); // 보이는 사진을 모두 뺐는데 서버에 더 남았으면 이어서 불러온다(실패하면 more_error 로 멈춘다)
  }, [kind, loadingMore, loadMore]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const rows = useMemo(() => buildTimelineRows(list.items), [list.items]);
  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const open = (item) => {
    setSelected(item);
    setMsgs((prev) => ({ ...prev, [item.attachment_id]: "" }));
  };
  const close = () => {
    if (busyId != null) return; // 빼는 중에는 닫지 않는다(결과를 보지 못하게 되지 않도록)
    setSelected(null);
  };

  /** 채팅의 그 메시지로 간다(뷰어를 닫고 가족 전체방을 연다). */
  const goOriginal = () => {
    if (!selected || busyId != null) return;
    const target = selected.message_id;
    setSelected(null);
    router.push(focusRoute({ id: target, room_kind: "family" }));
  };

  /** 내 사진을 타임라인에서 뺀다(흐름은 timeline.runExclude: 내 사진이 아니거나 처리 중이면 서버를 부르지 않는다). */
  const exclude = async () => {
    const item = selected;
    const id = item?.attachment_id;
    if (!id || busyId != null || working.current.has(id)) return;
    setBusyId(id);
    setMsgs((prev) => ({ ...prev, [id]: "" }));
    const out = await runExclude({ item, working: working.current, exclude: excludePhotoFromTimeline });
    if (!mounted.current) return;
    setBusyId(null);
    if (out.kind === "excluded" || out.kind === "gone") {
      list.remove(id); // 이미 타임라인에 없는 사진(지움·내 사진 아님)도 화면에서 뺀다
      setSelected((cur) => (cur?.attachment_id === id ? null : cur));
      setNotice(out.message);
    } else if (out.kind === "failed") {
      setMsgs((prev) => ({ ...prev, [id]: out.message })); // 일시 오류는 뷰어를 열어 둔 채 다시 시도할 수 있게 한다
    }
  };

  const cell = Math.floor((width - GAP * (TIMELINE_COLUMNS - 1)) / TIMELINE_COLUMNS);

  const actions = selected
    ? [
        { key: "original", label: ORIGINAL_LABEL, icon: "chatbubble-outline", onPress: goOriginal, disabled: busyId != null },
        ...(canExclude(selected) ? [{ key: "exclude", label: busyId === selectedId ? EXCLUDING_LABEL : EXCLUDE_LABEL, icon: "eye-off-outline", onPress: exclude, disabled: busyId != null }] : []),
      ]
    : [];

  let body;
  if (kind === "loading" || kind === "more") {
    body = (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  } else if (kind === "error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{list.error}</Text>
        <Button label="다시 시도" onPress={list.retry} />
      </View>
    );
  } else if (kind === "more_error") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{list.error}</Text>
        <Button label="다시 시도" onPress={list.loadMore} />
      </View>
    );
  } else if (kind === "empty") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{TIMELINE_EMPTY}</Text>
        <Text style={styles.hintText}>{TIMELINE_EMPTY_HINT}</Text>
      </View>
    );
  } else {
    body = (
      <FlatList
        data={rows}
        keyExtractor={(row) => row.key}
        renderItem={({ item: row }) => {
          if (row.type === "month") {
            return (
              <Text style={styles.month} accessibilityRole="header">
                {row.title}
              </Text>
            );
          }
          if (row.type === "day") return <Text style={styles.day}>{row.title}</Text>;
          return (
            <View style={styles.photoRow}>
              {row.items.map((item) => (
                <Pressable key={item.attachment_id} onPress={() => open(item)} accessibilityRole="imagebutton" accessibilityLabel={`${photoCaption(item)} 사진, 누르면 크게 봐요`}>
                  <AuthImage path={item.thumb_url} style={{ width: cell, height: cell }} />
                </Pressable>
              ))}
            </View>
          );
        }}
        onEndReached={() => {
          if (list.hasMore && !list.error) list.loadMore();
        }}
        onEndReachedThreshold={0.6}
        ListFooterComponent={
          list.loadingMore ? (
            <ActivityIndicator style={styles.footer} color={colors.accent} accessibilityLabel="더 불러오는 중" />
          ) : list.error ? (
            <View style={styles.footer}>
              <Text style={styles.emptyText}>{list.error}</Text>
              <Button label="다시 시도" onPress={list.loadMore} />
            </View>
          ) : null
        }
      />
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <Text style={styles.title} numberOfLines={1} accessibilityRole="header">
          {TIMELINE_TITLE}
        </Text>
      </View>
      <View style={[styles.body, { width }]}>{body}</View>
      {notice ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      ) : null}
      <PhotoViewer
        visible={selected != null}
        path={selected ? `/family-chat/photos/${encodeURIComponent(selected.attachment_id)}` : ""}
        onClose={close}
        caption={selected ? photoCaption(selected) : ""}
        actions={actions}
        actionNotice={selectedId ? (msgs[selectedId] ?? "") : ""}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background, alignItems: "center" },
  bar: { flexDirection: "row", alignItems: "center", alignSelf: "stretch", paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.divider },
  title: { ...font.cardTitle, color: colors.text, flex: 1, minWidth: 0 },
  body: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  hintText: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  month: { ...font.section, color: colors.text, paddingHorizontal: spacing.lg, paddingTop: spacing.xl, paddingBottom: spacing.xs },
  day: { ...font.bodyStrong, color: colors.textSub, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.xs },
  photoRow: { flexDirection: "row", gap: GAP, marginBottom: GAP },
  footer: { alignItems: "center", gap: spacing.sm, padding: spacing.lg },
  notice: { alignSelf: "stretch", alignItems: "center", paddingVertical: spacing.sm, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
});
