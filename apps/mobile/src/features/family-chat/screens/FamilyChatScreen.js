import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import UserAvatar from "@/shared/components/UserAvatar";
import Button from "@/shared/components/Button";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font, radius, spacing } from "@/theme";

import { getRoomInfo, listRooms, openDirectRoom, setRoomMuted } from "../api";
import { isNoGroup, previewText, roomErrorMessage } from "../chatUtils";
import ChatListHeader from "../components/ChatListHeader";
import ContentSearchSection from "../components/ContentSearchSection";
import EmptyChats from "../components/EmptyChats";
import NewChatPicker from "../components/NewChatPicker";
import SwipeableRoomRow from "../components/SwipeableRoomRow";
import { waitForPendingMarkRead } from "../pendingRead";
import { buildRoomRows, formatRoomTime, matchesQuery, MUTE_FAILED_NOTICE, pickableMembers, ROOM_REFRESH_MS, withRoomMuted } from "../listUtils";
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
  const [muteNotice, setMuteNotice] = useState("");
  const muteIntent = useRef(new Map()); // 저장 중인 방 id → 바꾸려는 muted. 같은 방을 저장하는 동안 다시 눌러도 무시하고, 그 사이 목록을 다시 읽어도 이 값을 지킨다
  const muteVersion = useRef(0); // 토글이 시작·끝날 때마다 올린다. 목록 읽기가 시작된 뒤에 바뀐 방은 늦게 온 옛 값으로 덮어쓰지 않는다
  const muteLast = useRef(new Map()); // 방 id → 마지막으로 정한 muted 와 그 때의 버전
  const [state, setState] = useState({ status: "loading", rooms: [], members: [], pickable: [], error: "" });
  const groupRef = useRef(null); // 마지막으로 읽은 가족 정보(방 이름·구성원). 주기 새로고침이 방 목록만 다시 읽을 때 쓴다
  const refreshing = useRef(false);

  /** 방 행에 "내가 방금 바꾼 알림 설정"을 덧입힌다(늦게 온 옛 값이 덮어쓰지 않게). */
  const withMuteOverrides = useCallback(
    (rows, startVersion) => [...muteLast.current].filter(([id, v]) => muteIntent.current.has(id) || v.version > startVersion).reduce((acc, [id, v]) => withRoomMuted(acc, id, v.muted), rows),
    [],
  );

  const load = useCallback(async () => {
    const startVersion = muteVersion.current;
    try {
      await waitForPendingMarkRead(); // 방을 막 나왔다면 읽음 올리기가 끝난 뒤에 숫자를 가져온다
      // 화면이 올 때마다 한 번(이후 방 목록만 주기적으로 `refreshRooms` 가 다시 읽는다).
      // 가족 정보는 필수(없으면 가족 없음/오류 화면), 방 목록이 실패해도 연락처는 보여 주고 다시 시도 안내를 띄운다
      const [group, rooms] = await Promise.all([getRoomInfo(), listRooms().catch((e) => ({ failed: e }))]);
      setListError(Array.isArray(rooms) ? "" : roomErrorMessage(rooms.failed));
      const people = Array.isArray(group.members) ? group.members : [];
      groupRef.current = group;
      setState({
        status: "ready",
        error: "",
        rooms: Array.isArray(rooms) ? withMuteOverrides(buildRoomRows(rooms, group, previewText, formatRoomTime), startVersion) : [],
        members: people.map((m) => ({ id: m.id, name: m.display_name || m.name, photoUrl: m.photo_url ?? null })),
        pickable: pickableMembers(people, group.my_id),
      });
    } catch (e) {
      setState(isNoGroup(e) ? { status: "none", rooms: [], members: [], pickable: [], error: "" } : { status: "error", rooms: [], members: [], pickable: [], error: roomErrorMessage(e) });
    }
  }, [withMuteOverrides]);

  /** 방 목록만 조용히 다시 읽는다(가족 정보는 그대로). 실패해도 화면은 그대로 두고, 이미 읽는 중이거나 앱이 뒤에 있으면 건너뛴다. */
  const refreshRooms = useCallback(async () => {
    if (refreshing.current || !groupRef.current || AppState.currentState === "background") return;
    refreshing.current = true;
    const startVersion = muteVersion.current;
    try {
      await waitForPendingMarkRead();
      const rooms = await listRooms();
      const rows = withMuteOverrides(buildRoomRows(rooms, groupRef.current, previewText, formatRoomTime), startVersion);
      setState((s) => (s.status === "ready" ? { ...s, rooms: rows } : s));
    } catch {
      // 다음 주기에 다시 시도한다
    } finally {
      refreshing.current = false;
    }
  }, [withMuteOverrides]);

  // 화면이 보이는 동안: 들어올 때 한 번 읽고, 이후 주기마다 방 목록을 다시 읽어 안 읽은 수가 하단 탭 숫자와 같이 올라가게 한다
  useFocusEffect(
    useCallback(() => {
      load();
      const timer = setInterval(refreshRooms, ROOM_REFRESH_MS);
      return () => clearInterval(timer);
    }, [load, refreshRooms]),
  );

  useEffect(() => {
    if (!muteNotice) return undefined;
    const timer = setTimeout(() => setMuteNotice(""), 2500);
    return () => clearTimeout(timer);
  }, [muteNotice]);

  /**
   * 방 알림 끄기/켜기: 화면에 먼저 반영하고 저장한다. 실패하면 되돌리고 안내 문구를 잠깐 보인다.
   * @param {{ id: string, muted?: boolean }} room
   */
  const toggleMute = async (room) => {
    if (muteIntent.current.has(room.id)) return;
    const next = room.muted !== true;
    muteIntent.current.set(room.id, next);
    muteVersion.current += 1;
    muteLast.current.set(room.id, { muted: next, version: muteVersion.current });
    setMuteNotice("");
    setState((s) => ({ ...s, rooms: withRoomMuted(s.rooms, room.id, next) }));
    try {
      await setRoomMuted(room.id, next);
    } catch {
      muteLast.current.set(room.id, { muted: !next, version: muteVersion.current + 1 });
      setState((s) => ({ ...s, rooms: withRoomMuted(s.rooms, room.id, !next) }));
      setMuteNotice(MUTE_FAILED_NOTICE);
    } finally {
      muteVersion.current += 1;
      muteIntent.current.delete(room.id);
    }
  };

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

        {muteNotice ? (
          <Text style={styles.muteNotice} accessibilityRole="alert" accessibilityLiveRegion="polite">
            {muteNotice}
          </Text>
        ) : null}

        {pickerOpen ? <NewChatPicker members={state.pickable} busyId={opening} error={pickError} onPick={startDirect} /> : null}

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

        <View>
          {state.status === "loading" ? (
            <Skeleton />
          ) : state.status === "none" ? (
            <EmptyChats onCreate={() => router.push("/family-create")} onJoin={() => router.push("/family-join")} />
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
            shown.map((room, i) => <SwipeableRoomRow key={room.id} room={room} divider={i < shown.length - 1} onPress={() => openRoom(room)} onToggleMute={() => toggleMute(room)} />)
          )}
        </View>

        {state.status === "ready" && searching && query.trim() ? (
          <ContentSearchSection search={search} roomLabel={(item) => searchRoomLabel(item, state.rooms, members)} onPick={(item) => router.push(focusRoute(item))} />
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
  muteNotice: { ...font.caption, color: colors.danger, textAlign: "center" },
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
