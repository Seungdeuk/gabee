import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, TextInput, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import IconButton from "@/shared/components/IconButton";
import Button from "@/shared/components/Button";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors, spacing } from "@/theme";

import { getRoomInfo, listMessages } from "../api";
import { formatListTime, isNoGroup, previewText, roomErrorMessage } from "../chatUtils";
import RoomRow from "../components/RoomRow";
import { contacts } from "../mock";

/**
 * 소통 탭: 실제 가족 채팅방 한 줄(가족 이름·마지막 말·시각)과 가족 연락처.
 * 화면에 올 때마다 한 번만 불러온다(폴링 없음). 줄을 누르면 채팅방으로 들어간다.
 */
export default function FamilyChatScreen() {
  const router = useRouter();
  const [query, setQuery] = useState("");
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
          time: message ? formatListTime(message.created_at) : "",
          unread: 0,
          tone: "blue",
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

  const shown = useMemo(() => {
    const room = state.room;
    if (!room) return [];
    const q = query.trim();
    return q && !room.name.includes(q) ? [] : [room];
  }, [query, state.room]);

  return (
    <Screen
      title="가족 채팅"
      subtitle="소중한 대화를 이어가요"
      right={
        <>
          <IconButton name="create-outline" label="새 대화" />
          <IconButton name="ellipsis-vertical" size={20} label="더 보기" />
        </>
      }
    >
      <View style={styles.search}>
        <Ionicons name="search-outline" size={20} color={colors.textMuted} />
        <TextInput
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="채팅방 검색"
          placeholderTextColor={colors.placeholder}
          accessibilityLabel="채팅 검색"
        />
      </View>

      <View>
        <SectionTitle title="채팅방" action="새 대화 +" />
        {state.status === "loading" ? (
          <ActivityIndicator style={styles.loading} color={colors.accent} accessibilityLabel="불러오는 중" />
        ) : state.status === "none" ? (
          <View style={styles.guide}>
            <Text style={styles.empty}>가족을 먼저 만들어 주세요</Text>
            <Button label="가족 만들기 · 참여하기" small onPress={() => router.push("/family")} />
          </View>
        ) : state.status === "error" ? (
          <View style={styles.guide}>
            <Text style={styles.empty}>{state.error}</Text>
            <Button label="다시 시도" small onPress={load} />
          </View>
        ) : shown.length === 0 ? (
          <Text style={styles.empty}>찾는 대화가 없어요</Text>
        ) : (
          shown.map((room, i) => <RoomRow key="family" room={room} last={i === shown.length - 1} onPress={() => router.push("/chat-room")} />)
        )}
      </View>

      <View style={styles.contacts}>
        <SectionTitle title="가족 연락처" action="전체 보기 →" />
        <View style={styles.contactCard}>
          <View style={styles.stack}>
            {contacts.map((c, i) => (
              <View key={c.id} style={i > 0 && styles.overlap}>
                <Avatar name={c.name} tone={c.tone} size={40} ring />
              </View>
            ))}
          </View>
          <Text style={styles.contactText}>
            <Text style={styles.contactStrong}>가족 {contacts.length}명</Text>
            <Text style={styles.contactMuted}> 등록됨</Text>
          </Text>
          <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  search: {
    height: 48,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: 14,
    backgroundColor: colors.card,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
  },
  searchInput: { flex: 1, minWidth: 0, fontSize: 15, color: colors.text, paddingVertical: 0 },
  loading: { paddingVertical: spacing.xxl },
  guide: { alignItems: "center", gap: spacing.md, paddingVertical: spacing.lg },
  empty: { paddingVertical: 24, textAlign: "center", color: colors.textMuted },
  contacts: { gap: 8 },
  contactCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: 20,
    backgroundColor: colors.card,
  },
  stack: { flexDirection: "row" },
  overlap: { marginLeft: -10 },
  contactText: { flex: 1, paddingLeft: 6, fontSize: 14 },
  contactStrong: { fontWeight: "600", color: colors.text },
  contactMuted: { color: colors.textMuted },
});
