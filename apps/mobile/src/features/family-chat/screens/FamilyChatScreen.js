import { Ionicons } from "@expo/vector-icons";
import { useMemo, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import SectionTitle from "@/shared/components/SectionTitle";
import { colors } from "@/theme";

import RoomRow from "../components/RoomRow";
import AiCard from "../components/AiCard";
import { contacts, rooms } from "../mock";

/** 소통 탭: 가족 채팅방 목록과 가족 연락처. TODO: 방을 누르면 대화 화면, 검색은 메시지 내용까지. */
export default function FamilyChatScreen() {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim();
    return q ? rooms.filter((r) => r.name.includes(q) || r.last.includes(q)) : rooms;
  }, [query]);

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
          placeholder="채팅방 또는 메시지 검색"
          placeholderTextColor={colors.placeholder}
          accessibilityLabel="채팅 검색"
        />
      </View>

      <AiCard />

      <View>
        <SectionTitle title="채팅방" action="새 대화 +" />
        {shown.length === 0 ? (
          <Text style={styles.empty}>찾는 대화가 없어요</Text>
        ) : (
          shown.map((room, i) => <RoomRow key={room.id} room={room} last={i === shown.length - 1} />)
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
