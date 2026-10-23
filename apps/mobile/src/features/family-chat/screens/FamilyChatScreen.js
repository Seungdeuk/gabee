import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, font, radius, spacing } from "@/theme";

import { getRoomInfo, listMessages } from "../api";
import { isNoGroup, previewText, roomErrorMessage } from "../chatUtils";
import ChatListHeader from "../components/ChatListHeader";
import EmptyChats from "../components/EmptyChats";
import RoomRow from "../components/RoomRow";
import { formatRoomTime, matchesQuery } from "../listUtils";

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
 * 소통 탭: 메신저 채팅 목록 모양의 가족 채팅방 한 줄과 가족 연락처.
 * 화면에 올 때마다 한 번만 불러온다(폴링 없음). 줄을 누르면 채팅방으로 들어간다.
 */
export default function FamilyChatScreen() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [newNotice, setNewNotice] = useState(false);
  const [state, setState] = useState({ status: "loading", room: null, error: "" });

  const load = useCallback(async () => {
    try {
      const group = await getRoomInfo();
      const rows = await listMessages({ latest: true, limit: 1 }).catch(() => []);
      const message = rows[rows.length - 1];
      setState({
        status: "ready",
        error: "",
        room: {
          name: group.name,
          last: previewText(message, group.my_id),
          time: message ? formatRoomTime(message.created_at) : "",
          count: Array.isArray(group.members) ? group.members.length : 0,
          tone: "blue",
          members: Array.isArray(group.members) ? group.members.map((m) => ({ id: m.id, name: m.display_name || m.name })) : [],
        },
      });
    } catch (e) {
      setState(isNoGroup(e) ? { status: "none", room: null, error: "" } : { status: "error", room: null, error: roomErrorMessage(e) });
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const members = state.room?.members ?? [];
  const shown = useMemo(() => (state.room && matchesQuery(state.room.name, query) ? [state.room] : []), [query, state.room]);

  const toggleSearch = () => {
    if (searching) setQuery("");
    setSearching((v) => !v);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <ChatListHeader
          searching={searching}
          query={query}
          onQuery={setQuery}
          onToggleSearch={toggleSearch}
          onNew={() => setNewNotice((v) => !v)}
        />

        {newNotice ? (
          <View style={styles.notice} accessibilityLiveRegion="polite">
            <Text style={styles.noticeText}>새 대화는 준비 중이에요</Text>
          </View>
        ) : null}

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
          ) : shown.length === 0 ? (
            <Text style={styles.empty}>찾는 대화가 없어요</Text>
          ) : (
            shown.map((room) => <RoomRow key="family" room={room} onPress={() => router.push("/chat-room")} />)
          )}
        </View>

        {members.length > 0 ? (
          <View style={styles.contacts}>
            <SectionTitle title="가족 연락처" action="전체 보기 →" />
            <View style={styles.contactCard}>
              <View style={styles.stack}>
                {members.slice(0, 5).map((m, i) => (
                  <View key={m.id} style={i > 0 && styles.overlap}>
                    <Avatar name={m.name} userId={m.id} size={40} ring />
                  </View>
                ))}
              </View>
              <Text style={styles.contactText}>
                <Text style={styles.contactStrong}>가족 {members.length}명</Text>
                <Text style={styles.contactMuted}> 등록됨</Text>
              </Text>
              <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
            </View>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.xl, paddingTop: spacing.xl, paddingBottom: spacing.xxl, gap: spacing.xl },
  notice: { alignItems: "center", paddingVertical: spacing.sm, borderRadius: radius.md, backgroundColor: colors.honeySoft },
  noticeText: { ...font.caption, color: colors.textSub },
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
