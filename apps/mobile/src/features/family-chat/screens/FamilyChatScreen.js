import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import UserAvatar from "@/shared/components/UserAvatar";
import Button from "@/shared/components/Button";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font, radius, spacing } from "@/theme";

import { getRoomInfo, listRooms, listTodos, openDirectRoom } from "../api";
import { isNoGroup, previewText, roomErrorMessage } from "../chatUtils";
import ChatListHeader from "../components/ChatListHeader";
import ContentSearchSection from "../components/ContentSearchSection";
import EmptyChats from "../components/EmptyChats";
import NewChatPicker from "../components/NewChatPicker";
import RoomRow from "../components/RoomRow";
import TodoCard from "../components/TodoCard";
import { waitForPendingMarkRead } from "../pendingRead";
import { OPEN_PREVIEW_LIMIT, openPreview } from "../todoUtils";
import { buildRoomRows, formatRoomTime, matchesQuery, pickableMembers } from "../listUtils";
import { focusRoute, searchRoomLabel } from "../searchUtils";
import useChatSearch from "../useChatSearch";

/** 로딩 중 행 모양 뼈대. */
function Skeleton() {
  return (
    <View accessibilityLabel="불러오는 중" style={styles.skeletons}>
      {[0, 1, 2].map((i) => (
        <View key={i} style={styles.skRow}>
          <View style={styles.skAvatar} />
          <View style={styles.skLines}>
            <View style={styles.skLineLong} />
            <View style={styles.skLineShort} />
          </View>
        </View>
      ))}
    </View>
  );
}

/**
 * 소통 탭: 메신저 채팅 목록 모양의 가족 전체방과 1:1 방, 가족 연락처.
 * 화면에 올 때마다 한 번만 불러온다(폴링 없음). 줄을 누르면 채팅방으로 들어가고, 새 대화 버튼으로 가족 구성원과 1:1 방을 연다.
 * 돋보기 검색은 방 이름 일치 아래에 "대화 내용" 검색 결과(서버 글자 일치)를 함께 보여 주고, 결과를 누르면 그 방의 해당 메시지 위치로 열린다.
 */
export default function FamilyChatScreen() {
  const router = useRouter();
  const search = useChatSearch();
  const query = search.query;
  const [searching, setSearching] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [opening, setOpening] = useState(null); // 1:1 방을 여는 중인 상대 id
  const [pickError, setPickError] = useState("");
  const openingRef = useRef(false); // 상태는 다시 그려진 뒤에야 바뀌어서, 같은 순간의 두 번째 누름은 ref 로 막는다
  const [listError, setListError] = useState("");
  const [todoPreview, setTodoPreview] = useState(null); // 가족 할 일 카드(실패하면 null 이라 카드만 숨는다)
  const [state, setState] = useState({ status: "loading", rooms: [], members: [], pickable: [], error: "" });

  const load = useCallback(async () => {
    try {
      await waitForPendingMarkRead(); // 방을 막 나왔다면 읽음 올리기가 끝난 뒤에 숫자를 가져온다
      // 화면이 올 때마다 한 번만(폴링 없음).
      // 가족 정보는 필수(없으면 가족 없음/오류 화면), 방 목록이 실패해도 연락처는 보여 주고 다시 시도 안내를 띄운다
      // 가족 할 일 카드는 따로 불러 목록 로딩에 영향을 주지 않는다(실패하면 카드만 숨긴다)
      listTodos("open", OPEN_PREVIEW_LIMIT)
        .then((todos) => setTodoPreview(openPreview(todos)))
        .catch(() => setTodoPreview(null));
      const [group, rooms] = await Promise.all([getRoomInfo(), listRooms().catch((e) => ({ failed: e }))]);
      setListError(Array.isArray(rooms) ? "" : roomErrorMessage(rooms.failed));
      const people = Array.isArray(group.members) ? group.members : [];
      setState({
        status: "ready",
        error: "",
        rooms: Array.isArray(rooms) ? buildRoomRows(rooms, group, previewText, formatRoomTime) : [],
        members: people.map((m) => ({ id: m.id, name: m.display_name || m.name, photoUrl: m.photo_url ?? null })),
        pickable: pickableMembers(people, group.my_id),
      });
    } catch (e) {
      setState(isNoGroup(e) ? { status: "none", rooms: [], members: [], pickable: [], error: "" } : { status: "error", rooms: [], members: [], pickable: [], error: roomErrorMessage(e) });
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const members = state.members;
  const shown = useMemo(() => state.rooms.filter((room) => matchesQuery(room.name, query)), [query, state.rooms]);

  const openRoom = (room) => router.push(room.kind === "direct" ? { pathname: "/chat-room", params: { roomId: room.id, peer: room.peerId ?? "" } } : "/chat-room");

  const startDirect = async (userId) => {
    if (openingRef.current) return;
    openingRef.current = true;
    setOpening(userId);
    setPickError("");
    try {
      const room = await openDirectRoom(userId);
      setPickerOpen(false);
      router.push({ pathname: "/chat-room", params: { roomId: room.id, peer: userId } });
    } catch (e) {
      setPickError(roomErrorMessage(e));
    } finally {
      openingRef.current = false;
      setOpening(null);
    }
  };

  const toggleSearch = () => {
    if (searching) search.reset();
    setSearching((v) => !v);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <ChatListHeader
          searching={searching}
          query={query}
          onQuery={search.setQuery}
          onToggleSearch={toggleSearch}
          onNew={() => {
            if (state.status !== "ready") return; // 가족 정보를 읽기 전에는 상대 목록이 없다
            setPickError("");
            setPickerOpen((v) => !v);
          }}
        />

        {pickerOpen ? <NewChatPicker members={state.pickable} busyId={opening} error={pickError} onPick={startDirect} /> : null}

        <View>
          {state.status === "loading" ? (
            <Skeleton />
          ) : state.status === "none" ? (
            <EmptyChats onCreate={() => router.push("/family")} onJoin={() => router.push("/family")} />
          ) : state.status === "error" ? (
            <View style={styles.banner} accessibilityRole="alert">
              <Text style={styles.bannerText}>{state.error}</Text>
              <Button label="다시 시도" small onPress={load} />
            </View>
          ) : listError ? (
            <View style={styles.banner} accessibilityRole="alert">
              <Text style={styles.bannerText}>{listError}</Text>
              <Button label="다시 시도" small onPress={load} />
            </View>
          ) : shown.length === 0 ? (
            query.trim() ? null : <Text style={styles.empty}>찾는 대화가 없어요</Text>
          ) : (
            shown.map((room) => <RoomRow key={room.id} room={room} onPress={() => openRoom(room)} />)
          )}
        </View>

        {state.status === "ready" && searching && query.trim() ? (
          <ContentSearchSection search={search} roomLabel={(item) => searchRoomLabel(item, state.rooms, members)} onPick={(item) => router.push(focusRoute(item))} />
        ) : null}

        {state.status === "ready" && todoPreview ? <TodoCard preview={todoPreview} onPress={() => router.push("/family-todos")} /> : null}

        {members.length > 0 ? (
          <View style={styles.contacts}>
            <SectionTitle title="가족 연락처" action="전체 보기 →" onAction={() => router.push("/family-contacts")} />
            <Pressable onPress={() => router.push("/family-contacts")} accessibilityRole="button" accessibilityLabel={`가족 연락처, 가족 ${members.length}명`} style={styles.contactCard}>
              <View style={styles.stack}>
                {members.slice(0, 5).map((m, i) => (
                  <View key={m.id} style={i > 0 && styles.overlap}>
                    <UserAvatar name={m.name} userId={m.id} photoUrl={m.photoUrl} size={40} ring />
                  </View>
                ))}
              </View>
              <Text style={styles.contactText}>
                <Text style={styles.contactStrong}>가족 {members.length}명</Text>
                <Text style={styles.contactMuted}> 등록됨</Text>
              </Text>
              <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
            </Pressable>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xl, paddingTop: spacing.xl, paddingBottom: spacing.xxl, gap: spacing.xl },
  skeletons: { gap: spacing.sm },
  skRow: { minHeight: 72, flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.sm },
  skAvatar: { width: 56, height: 56, borderRadius: radius.pill, backgroundColor: colors.surface },
  skLines: { flex: 1, gap: spacing.sm },
  skLineLong: { height: 14, width: "55%", borderRadius: radius.sm, backgroundColor: colors.surface },
  skLineShort: { height: 12, width: "80%", borderRadius: radius.sm, backgroundColor: colors.surface },
  banner: {
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.card,
    backgroundColor: colors.dangerSoft,
  },
  bannerText: { ...font.caption, color: colors.danger, textAlign: "center" },
  empty: { paddingVertical: spacing.xxl, textAlign: "center", color: colors.textMuted },
  contacts: { gap: spacing.sm },
  contactCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: radius.card,
    backgroundColor: colors.card,
  },
  stack: { flexDirection: "row" },
  overlap: { marginLeft: -10 },
  contactText: { flex: 1, paddingLeft: 6, fontSize: 14 },
  contactStrong: { fontWeight: "600", color: colors.text },
  contactMuted: { color: colors.textMuted },
});
