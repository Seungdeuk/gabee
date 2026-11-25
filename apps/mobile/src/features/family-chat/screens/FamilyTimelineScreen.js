import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { excludePhotoFromTimeline } from "../api";
import AlbumViewer from "../components/AlbumViewer";
import BundleCard from "../components/BundleCard";
import { EXCLUDED_ENTRY_LABEL } from "../photoChecks";
import { focusRoute } from "../searchUtils";
import {
  BUNDLE_HOLD_MS,
  EXCLUDE_LABEL,
  EXCLUDING_LABEL,
  ORIGINAL_LABEL,
  REFRESH_LABEL,
  SIMILAR_LABEL,
  TIMELINE_ANALYZING,
  TIMELINE_EMPTY,
  TIMELINE_EMPTY_HINT,
  TIMELINE_TITLE,
  analysisNotice,
  buildTimelineRows,
  canExclude,
  photoCaption,
  runExclude,
  splitHeldBack,
  timelineBodyKind,
  viewerAfterRemoval,
  viewerPhotos,
} from "../timeline";
import useFamilyTimeline from "../useFamilyTimeline";

const MAX_WIDTH = 600; // 웹처럼 넓은 화면에서 카드가 지나치게 커지지 않게 한다
const NOTICE_MS = 3000;

/**
 * 가족 타임라인: 가족 전체방에 올린 사진 중 일반 사진으로 확인된 것만 촬영일(없으면 보낸 날) 최신순으로 연·월·날짜별로 모아 보인다.
 * 같은 batch_id 로 올린 사진은 하나의 묶음 카드로 보인다(1장 큰 카드, 2장 나란히, 3장 위 한 장+아래 두 장, 4장 이상 2×2+N). 카드의 칸을 누르면 그 사진부터 묶음을 넘겨 본다.
 * 어떤 사진이 나오는지는 서버가 정한다(앱이 더하거나 숨기지 않는다). 쪽 경계에서 묶음이 갈라지지 않게 목록 끝에 걸친 묶음은 다음 쪽이 올 때까지 잠시 보류하되,
 * 다음 쪽 불러오기가 실패하거나 너무 오래 걸리면(BUNDLE_HOLD_MS) 가진 사진을 모두 보인다. 조회 실패는 빈 타임라인이 아니라 오류와 "다시 시도"로 보인다.
 */
export default function FamilyTimelineScreen() {
  const router = useRouter();
  const { width: windowWidth } = useWindowDimensions();
  const width = Math.min(windowWidth, MAX_WIDTH);
  const cardWidth = width - spacing.lg * 2;
  const list = useFamilyTimeline();
  const { retry } = list;
  const focusedBefore = useRef(false);
  useFocusEffect(
    useCallback(() => {
      // "뺀 사진"에서 다시 넣고 돌아오면 목록을 새로 받는다(처음 열 때는 훅이 이미 불러온다)
      if (focusedBefore.current) retry();
      focusedBefore.current = true;
    }, [retry]),
  );
  const [viewer, setViewer] = useState(null); // { photos, index }: 카드를 누른 순간의 사진들(보는 동안 카드가 자라도 번호가 밀리지 않는다)
  const [busyId, setBusyId] = useState(null); // 빼는 중인 사진 id(한 번에 한 장만)
  const [msgs, setMsgs] = useState({}); // 사진 id 별 뷰어 안 오류 문구(다른 사진의 결과가 지금 보는 사진의 문구를 지우지 않는다)
  const [notice, setNotice] = useState(""); // 화면 위 결과 안내(뷰어를 닫은 뒤에도 보인다)
  const [holdExpired, setHoldExpired] = useState(false); // 다음 쪽 요청이 너무 오래 걸려 보류를 풀었다
  const working = useRef(new Set()); // 처리 중인 사진 id: 상태가 반영되기 전에 두 번 눌러도 한 번만 보낸다
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true; // 개발 중 Fast Refresh·StrictMode 로 효과가 다시 돌아도 false 로 굳지 않게 한다
    return () => {
      mounted.current = false;
    };
  }, []);

  // 쪽 경계 보류: 더 받을 쪽이 있으면 끝에 걸친 묶음을 잠시 빼고 그린다(실패·시간 초과면 모두 보인다)
  const { shown } = useMemo(() => splitHeldBack(list.items, { hasMore: list.hasMore, failed: Boolean(list.error), expired: holdExpired }), [list.items, list.hasMore, list.error, holdExpired]);
  const view = useMemo(() => ({ ...list, items: shown }), [list, shown]);
  const kind = timelineBodyKind(view);
  const { loadMore, loadingMore } = list;
  useEffect(() => {
    if (kind === "more" && !loadingMore) loadMore(); // 보이는 사진이 없는데 서버에 더 남았으면(전부 보류 중이거나 모두 뺐거나) 이어서 불러온다(실패하면 more_error 로 멈춘다)
  }, [kind, loadingMore, loadMore]);

  useEffect(() => {
    if (!loadingMore) return undefined;
    const timer = setTimeout(() => setHoldExpired(true), BUNDLE_HOLD_MS); // 요청이 이만큼 걸리면 보류하던 묶음을 먼저 보인다
    return () => clearTimeout(timer);
  }, [loadingMore]);
  useEffect(() => {
    setHoldExpired(false); // 새 쪽이 오면(또는 사진이 바뀌면) 다음 끝 묶음에 대해 다시 보류할 수 있다
  }, [list.items.length]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(""), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const rows = useMemo(() => buildTimelineRows(shown), [shown]);
  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  /** 카드의 index 번째 사진부터 뷰어를 연다. */
  const openBundle = (row, index) => {
    setViewer({ photos: viewerPhotos(row), index });
    setMsgs({});
  };
  const close = () => {
    if (busyId != null) return; // 빼는 중에는 닫지 않는다(결과를 보지 못하게 되지 않도록)
    setViewer(null);
  };

  /** 채팅의 그 메시지로 간다(뷰어를 닫고 가족 전체방을 연다). */
  const goOriginal = (photo) => {
    if (busyId != null) return;
    setViewer(null);
    router.push(focusRoute({ id: photo.item.message_id, room_kind: "family" }));
  };

  /** 지금 보는 사진이 내 사진이면 타임라인에서 뺀다(흐름은 timeline.runExclude: 내 사진이 아니거나 처리 중이면 서버를 부르지 않는다). 남은 사진이 있으면 뷰어는 그대로 둔다. */
  const exclude = async (photo, index) => {
    const id = photo.id;
    if (busyId != null || working.current.has(id)) return;
    setBusyId(id);
    setMsgs((prev) => ({ ...prev, [id]: "" }));
    const out = await runExclude({ item: photo.item, working: working.current, exclude: excludePhotoFromTimeline });
    if (!mounted.current) return;
    setBusyId(null);
    if (out.kind === "excluded" || out.kind === "gone") {
      list.remove(id); // 이미 타임라인에 없는 사진(지움·내 사진 아님)도 화면에서 뺀다
      setViewer((cur) => viewerAfterRemoval(cur, id, index));
      setNotice(out.message);
    } else if (out.kind === "failed") {
      setMsgs((prev) => ({ ...prev, [id]: out.message })); // 일시 오류는 뷰어를 열어 둔 채 다시 시도할 수 있게 한다
    }
  };

  const actionsFor = (photo, index) => [
    { key: "original", label: ORIGINAL_LABEL, icon: "chatbubble-outline", onPress: () => goOriginal(photo), disabled: busyId != null },
    ...(canExclude(photo.item) ? [{ key: "exclude", label: busyId === photo.id ? EXCLUDING_LABEL : EXCLUDE_LABEL, icon: "eye-off-outline", onPress: () => exclude(photo, index), disabled: busyId != null }] : []),
  ];

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
  } else if (kind === "analyzing") {
    body = (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{TIMELINE_ANALYZING}</Text>
        <Text style={styles.hintText}>{analysisNotice(list)}</Text>
        <Button label={REFRESH_LABEL} onPress={list.retry} />
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
        ListHeaderComponent={
          analysisNotice(list) ? (
            <View style={styles.analysis} accessibilityLiveRegion="polite">
              <Text style={styles.analysisText}>{analysisNotice(list)}</Text>
              <Button label={REFRESH_LABEL} onPress={list.retry} />
            </View>
          ) : null
        }
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
            <View style={styles.bundleRow}>
              <BundleCard photos={row.photos} width={cardWidth} onOpen={(i) => openBundle(row, i)} />
              {row.similar ? (
                <Text style={styles.similar}>
                  {SIMILAR_LABEL} {row.photos.length}장
                </Text>
              ) : null}
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
        <IconButton name="eye-off-outline" label={EXCLUDED_ENTRY_LABEL} onPress={() => router.push("/chat-photo-review?kind=excluded")} />
      </View>
      <View style={[styles.body, { width }]}>{body}</View>
      {notice ? (
        <View style={styles.notice} accessibilityLiveRegion="polite">
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      ) : null}
      <AlbumViewer
        visible={viewer != null}
        photos={viewer?.photos ?? []}
        startIndex={viewer?.index ?? 0}
        onClose={close}
        captionFor={(photo) => photoCaption(photo.item)}
        actionsFor={actionsFor}
        actionNoticeFor={(photo) => msgs[photo.id] ?? ""}
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
  bundleRow: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  similar: { ...font.caption, color: colors.textMuted, paddingTop: spacing.xs },
  analysis: { alignItems: "center", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.honeySoft },
  analysisText: { ...font.caption, color: colors.textSub, textAlign: "center" },
  footer: { alignItems: "center", gap: spacing.sm, padding: spacing.lg },
  notice: { alignSelf: "stretch", alignItems: "center", paddingVertical: spacing.sm, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
});
