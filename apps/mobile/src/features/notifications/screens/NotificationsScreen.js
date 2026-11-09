import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, BackHandler, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { backTarget, lastTabPath } from "@/shared/navigation/lastTab";
import { colors, font, radius, spacing } from "@/theme";

import { listNotifications, markAllRead, markRead } from "../api";
import NotificationRow from "../components/NotificationRow";
import { KIND_META, KIND_ORDER, routeFor } from "../kinds";

const PAGE = 30;

/** 알림함: 분류 칩으로 거르고, 누르면 읽음 처리 후 관련 화면으로 이동한다. */
export default function NotificationsScreen() {
  const router = useRouter();
  const [kind, setKind] = useState(null); // null = 전체
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [loadingMore, setLoadingMore] = useState(false);
  const requestId = useRef(0); // 분류를 빠르게 바꿨을 때 늦게 온 옛 응답이 덮어쓰지 않게 한다

  /**
   * 뒤로 가기: 돌아갈 화면이 있으면 뒤로, 없으면(푸시로 바로 열린 경우) 마지막으로 보던 탭으로 간다.
   * @returns {void}
   */
  const goBack = useCallback(() => {
    const target = backTarget(router.canGoBack(), lastTabPath());
    if (target === "back") router.back();
    else router.replace(target);
  }, [router]);

  // 안드로이드 뒤로 가기 버튼: 돌아갈 화면이 없을 때만 앱이 종료되지 않게 마지막 탭으로 보낸다(있으면 기본 동작)
  useFocusEffect(
    useCallback(() => {
      const sub = BackHandler.addEventListener("hardwareBackPress", () => {
        if (router.canGoBack()) return false;
        router.replace(lastTabPath());
        return true;
      });
      return () => sub.remove();
    }, [router]),
  );

  const load = useCallback(async (nextKind) => {
    const id = ++requestId.current;
    setStatus("loading");
    try {
      const page = await listNotifications({ kind: nextKind, limit: PAGE });
      if (id !== requestId.current) return;
      setItems(page.items);
      setCursor(page.next_cursor);
      setStatus("ready");
    } catch {
      if (id === requestId.current) setStatus("error");
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load(kind);
    }, [load, kind]),
  );

  const loadMore = async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await listNotifications({ kind, limit: PAGE, cursor });
      setItems((prev) => [...prev, ...page.items]);
      setCursor(page.next_cursor);
    } catch {
      // 더 불러오지 못해도 이미 받은 목록은 그대로 둔다
    } finally {
      setLoadingMore(false);
    }
  };

  const open = async (item) => {
    if (!item.read_at) {
      setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)));
      markRead(item.id).catch(() => {}); // 못 보내도 이동은 막지 않는다. 다음에 열 때 서버 상태로 다시 맞춘다
    }
    const path = routeFor(item);
    if (path) router.push(path);
  };

  const readAll = async () => {
    try {
      await markAllRead(kind ?? undefined);
      await load(kind);
    } catch {
      setStatus("error");
    }
  };

  const hasUnread = items.some((n) => !n.read_at);

  return (
    <Screen
      title="알림"
      subtitle="가족과 일어난 일을 모아 봐요"
      centered
      left={<IconButton name="chevron-back" label="뒤로" onPress={goBack} />}
      pinned={
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[styles.chips, styles.chipsCenter]} style={styles.chipsBar}>
          <Chip label="전체" selected={kind === null} onPress={() => setKind(null)} />
          {KIND_ORDER.map((k) => (
            <Chip key={k} label={KIND_META[k].label} selected={kind === k} onPress={() => setKind(k)} />
          ))}
        </ScrollView>
      }
    >
      {hasUnread ? (
        <View style={styles.actions}>
          <Button label="모두 읽음" variant="ghost" small onPress={readAll} testID="read-all" />
        </View>
      ) : null}
      {status === "loading" && items.length === 0 ? <ActivityIndicator color={colors.primary} style={styles.center} /> : null}
      {status === "error" ? (
        <View style={styles.center}>
          <Text style={styles.empty}>알림을 불러오지 못했어요</Text>
          <Button label="다시 시도" variant="secondary" small onPress={() => load(kind)} testID="retry" />
        </View>
      ) : null}
      {status === "ready" && items.length === 0 ? <Text style={[styles.empty, styles.center]}>아직 알림이 없어요</Text> : null}
      <View style={styles.list}>
        {items.map((item) => (
          <NotificationRow key={item.id} item={item} onPress={() => open(item)} />
        ))}
      </View>
      {cursor ? (
        <View style={styles.actions}>
          <Button label={loadingMore ? "불러오는 중…" : "더 보기"} variant="secondary" small disabled={loadingMore} onPress={loadMore} />
        </View>
      ) : null}
    </Screen>
  );
}

function Chip({ label, selected, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={[styles.chip, selected && styles.chipSelected]}
    >
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chipsBar: { backgroundColor: colors.background },
  chips: { gap: spacing.sm, paddingHorizontal: spacing.xl, paddingVertical: spacing.sm }, // Screen 의 pinned 영역은 좌우 여백이 없어 직접 두고, 폭이 모자라면 가로로 민다
  chipsCenter: { flexGrow: 1, justifyContent: "center" }, // 칩이 화면보다 좁으면 가운데, 넘치면 처음부터 가로로 민다
  chip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipSelected: { backgroundColor: colors.surfaceStrong },
  chipText: { ...font.caption, color: colors.textMuted },
  chipTextSelected: { color: colors.text, fontFamily: font.bodyStrong.fontFamily },
  actions: { flexDirection: "row", justifyContent: "flex-end", paddingVertical: spacing.sm },
  list: { gap: spacing.sm },
  center: { alignItems: "center", gap: spacing.md, paddingVertical: spacing.xxl },
  empty: { ...font.body, color: colors.textMuted, textAlign: "center" },
});
