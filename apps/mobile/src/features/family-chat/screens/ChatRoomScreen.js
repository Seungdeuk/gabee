import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, spacing } from "@/theme";

import { buildItems, canSend, trimDraft } from "../chatUtils";
import AiPanel from "../components/AiPanel";
import Composer from "../components/Composer";
import MessageBubble from "../components/MessageBubble";
import useChatMessages, { useRoomInfo } from "../useChatMessages";

const NEAR = 120; // 바닥/맨 위에서 이 정도 안이면 "근처"로 본다

/** 가운데 안내(로딩·오류·그룹 없음). */
function Center({ children }) {
  return <View style={styles.center}>{children}</View>;
}

/** 실제 가족 채팅방: 메시지 목록, 입력창, AI 도우미(✨) 시트. */
export default function ChatRoomScreen() {
  const router = useRouter();
  const info = useRoomInfo();
  const chat = useChatMessages({ me: info.me, enabled: info.status === "ready" });
  const [draft, setDraft] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const listRef = useRef(null);
  const nearBottom = useRef(true);
  const scrollPos = useRef({ y: 0, height: 0 }); // 웹은 maintainVisibleContentPosition 이 없어 이전 대화가 위에 붙을 때 위치를 직접 지킨다
  const olderRequested = useRef(false);

  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const scrollToEnd = useCallback((animated) => listRef.current?.scrollToEnd({ animated }), []);

  const onScroll = useCallback(
    ({ nativeEvent: { contentOffset, contentSize, layoutMeasurement } }) => {
      nearBottom.current = contentSize.height - (contentOffset.y + layoutMeasurement.height) < NEAR;
      scrollPos.current.y = contentOffset.y;
      if (contentOffset.y < NEAR) {
        olderRequested.current = true;
        chat.loadOlder();
      }
    },
    [chat],
  );

  const onSend = () => {
    if (!canSend(draft)) return;
    const text = trimDraft(draft);
    setDraft("");
    nearBottom.current = true;
    chat.send(text);
  };

  const pickReply = (text) => {
    setDraft((prev) => (prev.trim() ? `${prev} ${text}` : text));
    setAiOpen(false);
  };

  const items = buildItems(chat.messages);
  const members = info.room?.members?.length ?? 0;

  const header = (
    <View style={styles.bar}>
      <IconButton name="chevron-back" label="뒤로" onPress={back} />
      <View style={styles.titleBox}>
        <Text style={styles.title} numberOfLines={1}>
          {info.room?.name ?? "가족 채팅"}
        </Text>
        {info.room ? <Text style={styles.subtitle}>구성원 {members}명</Text> : null}
      </View>
      <IconButton name="sparkles-outline" label="AI 도우미 열기" onPress={() => setAiOpen(true)} disabled={info.status !== "ready"} />
    </View>
  );

  let body;
  if (info.status === "loading") {
    body = (
      <Center>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </Center>
    );
  } else if (info.status === "none") {
    body = (
      <Center>
        <Text style={styles.emptyTitle}>가족을 먼저 만들어 주세요</Text>
        <Text style={styles.emptyText}>가족을 만들거나 초대 코드로 참여하면 함께 대화할 수 있어요.</Text>
        <Button label="가족 만들기 · 참여하기" onPress={() => router.push("/family")} />
      </Center>
    );
  } else if (info.status === "error") {
    body = (
      <Center>
        <Text style={styles.emptyText}>{info.error}</Text>
        <Button label="다시 시도" onPress={info.reload} />
      </Center>
    );
  } else if (chat.status === "loading") {
    body = (
      <Center>
        <ActivityIndicator color={colors.accent} accessibilityLabel="대화를 불러오는 중" />
      </Center>
    );
  } else if (chat.status === "error" && chat.messages.length === 0) {
    body = (
      <Center>
        <Text style={styles.emptyText}>{chat.error}</Text>
        <Button label="다시 시도" onPress={chat.retry} />
      </Center>
    );
  } else {
    body = (
      <>
        {chat.error ? (
          <View style={styles.banner} accessibilityLiveRegion="polite">
            <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
            <Text style={styles.bannerText} numberOfLines={2}>
              {chat.error}
            </Text>
            <Pressable onPress={chat.retry} accessibilityRole="button" accessibilityLabel="다시 시도" style={styles.bannerBtn}>
              <Text style={styles.bannerAction}>다시 시도</Text>
            </Pressable>
          </View>
        ) : null}
        <FlatList
          ref={listRef}
          style={styles.list}
          data={items}
          keyExtractor={(it) => it.key}
          renderItem={({ item }) =>
            item.type === "day" ? (
              <View style={styles.dayWrap}>
                <Text style={styles.day}>{item.label}</Text>
              </View>
            ) : (
              <MessageBubble
                message={item.message}
                mine={item.message.user_id === info.me?.id}
                showName={item.showName}
                onRetry={chat.resend}
                onDiscard={chat.discard}
              />
            )
          }
          ListHeaderComponent={chat.loadingOlder ? <ActivityIndicator style={styles.older} color={colors.accent} accessibilityLabel="이전 대화를 불러오는 중" /> : null}
          ListEmptyComponent={
            <View style={styles.emptyList}>
              <Text style={styles.emptyTitle}>아직 대화가 없어요</Text>
              <Text style={styles.emptyText}>첫 메시지를 보내 보세요.</Text>
            </View>
          }
          onScroll={onScroll}
          scrollEventThrottle={100}
          onContentSizeChange={(_, height) => {
            const grew = height - scrollPos.current.height;
            if (Platform.OS === "web" && olderRequested.current && grew > 0 && scrollPos.current.height > 0 && !nearBottom.current) {
              olderRequested.current = false;
              listRef.current?.scrollToOffset({ offset: scrollPos.current.y + grew, animated: false });
            } else if (nearBottom.current) {
              scrollToEnd(false);
            }
            scrollPos.current.height = height;
          }}
          maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={styles.listContent}
        />
        <Composer value={draft} onChangeText={setDraft} onSend={onSend} />
      </>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      {header}
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        {body}
      </KeyboardAvoidingView>
      <AiPanel visible={aiOpen} onClose={() => setAiOpen(false)} onPickReply={pickReply} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  titleBox: { flex: 1, minWidth: 0, alignItems: "center" },
  title: { ...font.cardTitle, color: colors.text },
  subtitle: { ...font.tab, color: colors.textMuted },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  emptyList: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl * 2 },
  list: { flex: 1 },
  listContent: { paddingVertical: spacing.md },
  older: { paddingVertical: spacing.md },
  dayWrap: { alignItems: "center", paddingVertical: spacing.md },
  day: { ...font.tab, color: colors.textMuted, backgroundColor: colors.honeySoft, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: 12, overflow: "hidden" },
  banner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.dangerSoft },
  bannerText: { flex: 1, ...font.caption, color: colors.danger },
  bannerBtn: { minHeight: 36, justifyContent: "center" },
  bannerAction: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
