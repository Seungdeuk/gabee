import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Button from "@/shared/components/Button";
import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { buildItems, canSend, lastId, photoSendErrorMessage, trimDraft, unreadCount } from "../chatUtils";
import AiPanel from "../components/AiPanel";
import ChatSearchBar from "../components/ChatSearchBar";
import ChatSearchResults from "../components/ChatSearchResults";
import Composer from "../components/Composer";
import LiveReturnButton from "../components/LiveReturnButton";
import MessageBubble from "../components/MessageBubble";
import RoomDrawer from "../components/RoomDrawer";
import { parseFocusParam, roomSearchOptions, shouldLoadNewer } from "../searchUtils";
import useChatMessages, { useRoomInfo } from "../useChatMessages";
import useChatSearch, { useFamilyRoomId } from "../useChatSearch";
import { memberName } from "../listUtils";
import { pickChatPhoto } from "../pickPhoto";
import useReadMarker from "../useReadMarker";

const NEAR = 120; // 바닥/맨 위에서 이 정도 안이면 "근처"로 본다
const FAR = 400; // 바닥에서 이 이상 올라와 있으면 "맨 아래로" 버튼을 보여 준다
const HIGHLIGHT_MS = 2000; // 검색 결과로 이동한 메시지를 강조해 두는 시간
const SETTLE_MS = 600; // 이동 직후 이 시간 동안은 위로 자동 불러오기를 막아 이동 위치가 밀리지 않게 한다
const NO_MESSAGES = []; // 과거 창을 보는 동안 읽음 처리에 넘기는 빈 목록

/** 가운데 안내(로딩·오류·그룹 없음). */
function Center({ children }) {
  return <View style={styles.center}>{children}</View>;
}

/**
 * 실제 채팅방: 메시지 목록, 입력창, AI 도우미(✨) 시트.
 * 경로 인자 roomId 가 없으면 가족 전체방이고, 있으면 그 방(1:1)이다. peer 는 1:1 상대의 id 로 방 이름을 정하는 데만 쓴다.
 * 1:1 대화는 AI 로 보내지 않아서 1:1 방에는 AI 도우미 버튼이 없다.
 * 상단 돋보기(대화 검색)는 이 방 안에서 글자 일치로 찾고, 결과를 누르면 그 메시지 위치(과거 창)로 이동한다. 경로 인자 focus 가 있으면 처음부터 그 위치로 열린다.
 * 과거 창을 보는 동안은 "최신 대화로 이동" 버튼이 뜨고, 새 메시지 확인과 읽음 처리는 멈춘다.
 */
export default function ChatRoomScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const roomId = typeof params.roomId === "string" && params.roomId ? params.roomId : null;
  const peerId = typeof params.peer === "string" ? params.peer : null;
  const direct = roomId != null;
  const initialFocus = parseFocusParam(params.focus);
  const info = useRoomInfo();
  const chat = useChatMessages({ me: info.me, enabled: info.status === "ready", roomId, initialFocus });
  // 과거 창을 보는 동안은 읽음 위치를 올리지 않는다(보고 있지 않은 최신 메시지를 읽음 처리하면 안 된다)
  useReadMarker({ messages: chat.focusing ? NO_MESSAGES : chat.messages, myId: info.me?.id, enabled: info.status === "ready", roomId });
  const familyRoom = useFamilyRoomId(!direct); // 가족 전체방은 경로에 방 id 가 없어 방 목록에서 알아낸다
  const search = useChatSearch(roomSearchOptions(roomId, familyRoom.id)); // 방 id 를 알기 전에는 검색하지 않는다(모든 방 검색으로 떨어지지 않게)
  const [searchOpen, setSearchOpen] = useState(false);
  const [highlightId, setHighlightId] = useState(null);
  const [goingLive, setGoingLive] = useState(false);
  const [draft, setDraft] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const listRef = useRef(null);
  const nearBottom = useRef(initialFocus == null);
  const itemsRef = useRef([]);
  const settling = useRef(initialFocus != null);
  const focusRetry = useRef(0);
  const scrollPos = useRef({ y: 0, height: 0 }); // 웹은 maintainVisibleContentPosition 이 없어 이전 대화가 위에 붙을 때 위치를 직접 지킨다
  const olderRequested = useRef(false);
  const picking = useRef(false); // 사진 고르는 중 중복 누름 방지(ref)
  const [pickingUi, setPicking] = useState(false);
  const [far, setFar] = useState(false); // 바닥에서 멀리 올라와 있는지
  const [hasNew, setHasNew] = useState(false); // 올라와 있는 동안 새 메시지가 왔는지
  const [drawerOpen, setDrawerOpen] = useState(false);
  const newestId = useRef(0);
  // 채팅 메시지 응답에는 사진 주소가 없어서 구성원 목록에서 user_id 로 찾는다
  const photoById = useMemo(() => Object.fromEntries((info.room?.members ?? []).map((m) => [m.id, m.photo_url ?? null])), [info.room]);


  const back = () => (router.canGoBack() ? router.back() : router.replace("/family-chat"));

  const scrollToEnd = useCallback((animated) => listRef.current?.scrollToEnd({ animated }), []);

  const onScroll = useCallback(
    ({ nativeEvent: { contentOffset, contentSize, layoutMeasurement } }) => {
      const fromBottom = contentSize.height - (contentOffset.y + layoutMeasurement.height);
      nearBottom.current = fromBottom < NEAR;
      setFar(fromBottom > FAR);
      if (fromBottom <= FAR) setHasNew(false);
      scrollPos.current.y = contentOffset.y;
      if (contentOffset.y < NEAR && !settling.current) {
        olderRequested.current = true;
        chat.loadOlder();
      }
      if (shouldLoadNewer({ focusing: chat.focusing, fromBottom, near: NEAR, busy: false })) chat.loadNewer(); // 아래 끝에 닿으면 이후 대화를 이어 받고, 라이브 끝이면 자동으로 라이브로 돌아간다
    },
    [chat],
  );

  const onSend = () => {
    if (!canSend(draft)) return;
    const text = trimDraft(draft);
    setDraft("");
    nearBottom.current = true;
    chat.send(text).then((started) => {
      if (!started) setDraft((prev) => prev || text); // 보내지 못했으면(최신 대화로 돌아가지 못함 등) 쓴 글을 되돌려 놓는다
    });
  };

  /** 갤러리에서 사진 한 장을 골라 보낸다. 고르는 동안·보내는 동안은 다시 누를 수 없다. */
  const onPickPhoto = async () => {
    if (picking.current || chat.photoBusy) return;
    picking.current = true;
    setPicking(true);
    chat.setPhotoError("");
    try {
      const asset = await pickChatPhoto();
      if (!asset) return;
      nearBottom.current = true;
      if (await chat.sendImage(asset)) scrollToEnd(true);
    } catch (e) {
      chat.setPhotoError(photoSendErrorMessage(e));
    } finally {
      picking.current = false;
      setPicking(false);
    }
  };

  const pickReply = (text) => {
    setDraft((prev) => (prev.trim() ? `${prev} ${text}` : text));
    setAiOpen(false);
  };

  useEffect(() => {
    const newest = lastId(chat.messages);
    if (newest > newestId.current && newestId.current > 0 && !nearBottom.current) setHasNew(true);
    newestId.current = Math.max(newestId.current, newest);
  }, [chat.messages]);

  // 검색 결과(또는 focus 인자)로 이동: 목록이 그 창으로 바뀌면 해당 메시지로 스크롤하고 잠깐 강조한다
  useEffect(() => {
    const target = chat.focusTarget;
    if (!target) return undefined;
    nearBottom.current = false;
    settling.current = true;
    focusRetry.current = 0;
    setHasNew(false);
    setHighlightId(target.id);
    const scroll = setTimeout(() => {
      const index = itemsRef.current.findIndex((it) => it.type === "message" && String(it.message.id) === String(target.id));
      if (index >= 0) listRef.current?.scrollToIndex({ index, viewPosition: 0.35, animated: false });
    }, 0);
    const settle = setTimeout(() => {
      settling.current = false;
    }, SETTLE_MS);
    const clear = setTimeout(() => setHighlightId(null), HIGHLIGHT_MS);
    return () => {
      clearTimeout(scroll);
      clearTimeout(settle);
      clearTimeout(clear);
    };
  }, [chat.focusTarget]);

  // 포커스 실패로 최근 대화로 복구됐을 때: 위로 불러오기 잠금을 풀고 맨 아래로 간다
  useEffect(() => {
    if (chat.recovered === 0) return undefined;
    settling.current = false;
    nearBottom.current = true;
    const t = setTimeout(() => scrollToEnd(false), 50);
    return () => clearTimeout(t);
  }, [chat.recovered, scrollToEnd]);

  /** 아직 그려지지 않은 줄로 바로 갈 수 없을 때: 대략 위치로 먼저 간 뒤 다시 시도한다(최대 4번). */
  const onScrollToIndexFailed = useCallback(({ index, averageItemLength }) => {
    focusRetry.current += 1;
    if (focusRetry.current > 4) return;
    listRef.current?.scrollToOffset({ offset: Math.max(0, averageItemLength * index), animated: false });
    setTimeout(() => listRef.current?.scrollToIndex({ index, viewPosition: 0.35, animated: false }), 120);
  }, []);

  const closeSearch = () => {
    setSearchOpen(false);
    search.reset();
  };

  /** 결과를 누르면 검색 모드를 닫고(검색어·결과는 남겨 다시 열면 이어서 볼 수 있다) 그 메시지 위치로 이동한다. */
  const pickResult = (item) => {
    setSearchOpen(false);
    chat.focusOn(item.id);
  };

  const goLive = async () => {
    if (goingLive) return;
    setGoingLive(true);
    setHighlightId(null);
    nearBottom.current = true;
    const ok = await chat.returnToLive();
    setGoingLive(false);
    if (ok) setTimeout(() => scrollToEnd(false), 50);
    else nearBottom.current = false;
  };

  const jumpToEnd = () => {
    nearBottom.current = true;
    setHasNew(false);
    setFar(false);
    scrollToEnd(true);
  };

  const items = buildItems(chat.messages);
  itemsRef.current = items;
  const members = info.room?.members?.length ?? 0;
  const peer = direct ? info.room?.members?.find((m) => m.id === peerId) : null;
  const title = direct ? (info.room ? memberName(peer) : "1:1 대화") : (info.room?.name ?? "가족 채팅");

  const header = searchOpen ? (
    <ChatSearchBar value={search.query} onChange={search.setQuery} onClose={closeSearch} />
  ) : (
    <>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="뒤로" onPress={back} />
        <View style={styles.titleBox}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {info.room && !direct ? (
            <Text style={styles.count} accessibilityLabel={`구성원 ${members}명`}>
              {members}
            </Text>
          ) : null}
        </View>
        <IconButton name="search-outline" label="대화 검색" onPress={() => setSearchOpen(true)} disabled={info.status !== "ready"} />
        {direct ? null : <IconButton name="sparkles-outline" label="AI 도우미 열기" onPress={() => setAiOpen(true)} disabled={info.status !== "ready"} />}
        <IconButton name="ellipsis-vertical" label="채팅방 메뉴" onPress={() => setDrawerOpen(true)} />
      </View>
    </>
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
        <View style={styles.listArea}>
        <FlatList
          ref={listRef}
          style={styles.list}
          data={items}
          keyExtractor={(it) => it.key}
          renderItem={({ item }) =>
            item.type === "day" ? (
              <View style={styles.dayWrap}>
                <Text style={styles.day} accessibilityRole="header">
                  {item.label}
                </Text>
              </View>
            ) : (
              <MessageBubble
                message={item.message}
                mine={item.message.user_id === info.me?.id}
                showName={item.showName}
                showTime={item.showTime}
                unread={unreadCount(item.message, info.me, chat.readStates)}
                photoUrl={photoById[item.message.user_id]}
                highlighted={highlightId != null && String(item.message.id) === String(highlightId)}
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
          onScrollToIndexFailed={onScrollToIndexFailed}
          scrollEventThrottle={100}
          onContentSizeChange={(_, height) => {
            const grew = height - scrollPos.current.height;
            if (Platform.OS === "web" && olderRequested.current && grew > 0 && scrollPos.current.height > 0 && !nearBottom.current) {
              olderRequested.current = false;
              listRef.current?.scrollToOffset({ offset: scrollPos.current.y + grew, animated: false });
            } else if (nearBottom.current && !chat.focusing) {
              scrollToEnd(false);
            }
            scrollPos.current.height = height;
          }}
          maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={styles.listContent}
        />
        {chat.focusing ? <LiveReturnButton onPress={goLive} busy={goingLive || chat.loadingNewer} /> : null}
        {far && !chat.focusing ? (
          <Pressable
            onPress={jumpToEnd}
            accessibilityRole="button"
            accessibilityLabel={hasNew ? "새 메시지, 맨 아래로" : "맨 아래로"}
            style={[styles.jump, hasNew && styles.jumpNew]}
          >
            <Ionicons name="arrow-down" size={20} color={colors.text} />
          </Pressable>
        ) : null}
        </View>
        <Composer
          value={draft}
          onChangeText={setDraft}
          onSend={onSend}
          onPickPhoto={onPickPhoto}
          photoBusy={pickingUi || chat.photoBusy}
          photoError={chat.photoError}
          onDismissPhotoError={() => chat.setPhotoError("")}
        />
      </>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      {header}
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        {body}
        {searchOpen && info.status === "ready" ? (
          <View style={styles.searchLayer}>
            <ChatSearchResults search={search} onPick={pickResult} scope={familyRoom} />
          </View>
        ) : null}
      </KeyboardAvoidingView>
      <RoomDrawer visible={drawerOpen} onClose={() => setDrawerOpen(false)} room={info.room} roomId={roomId} peerId={peerId} myId={info.me?.id} onOpenSearch={() => setSearchOpen(true)} />
      {direct ? null : <AiPanel visible={aiOpen} onClose={() => setAiOpen(false)} onPickReply={pickReply} />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  searchLayer: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, backgroundColor: colors.background }, // 목록을 그대로 둔 채 위에 덮어, 검색을 닫아도 보던 위치가 유지된다
  bar: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  titleBox: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: spacing.xs },
  title: { ...font.cardTitle, color: colors.text, flexShrink: 1 },
  count: { ...font.caption, color: colors.textMuted },
  listArea: { flex: 1 },
  jump: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.lg,
    width: 40,
    height: 40,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
  },
  jumpNew: { backgroundColor: colors.peach, borderColor: colors.peach },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyTitle: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  emptyList: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.xxl * 2 },
  list: { flex: 1, backgroundColor: colors.background },
  listContent: { paddingVertical: spacing.md },
  older: { paddingVertical: spacing.md },
  dayWrap: { alignItems: "center", paddingVertical: spacing.md },
  day: { ...font.tab, color: colors.textMuted, backgroundColor: colors.surface, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.pill, overflow: "hidden" },
  banner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, backgroundColor: colors.dangerSoft },
  bannerText: { flex: 1, ...font.caption, color: colors.danger },
  bannerBtn: { minHeight: 36, justifyContent: "center" },
  bannerAction: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
