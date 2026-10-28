import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, TextInput, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import SettingsButton, { SETTINGS_EDGE_GAP, SETTINGS_RAISE } from "@/shared/components/SettingsButton";
import { colors, font, spacing } from "@/theme";

/**
 * 소통 탭 상단: 큰 제목 "우리 도란도란"과 오른쪽 검색·새 대화 버튼, 검색을 누르면 펼쳐지는 입력줄.
 * 검색 입력은 방 이름과 대화 내용을 함께 찾는다(대화 내용 결과는 화면이 입력값으로 따로 불러와 보여 준다).
 * @param {{ searching: boolean, query: string, onQuery: (text: string) => void, onToggleSearch: () => void, onNew: () => void }} props
 */
export default function ChatListHeader({ searching, query, onQuery, onToggleSearch, onNew }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.top}>
        <Text style={styles.title} accessibilityRole="header">
          우리 도란도란
        </Text>
        <View style={styles.buttons}>
          <IconButton name={searching ? "close" : "search-outline"} label={searching ? "검색 닫기" : "검색"} onPress={onToggleSearch} />
          <IconButton name="create-outline" label="새 대화" onPress={onNew} />
          <SettingsButton />
        </View>
      </View>
      {searching ? (
        <View style={styles.search}>
          <Ionicons name="search-outline" size={20} color={colors.textMuted} />
          <TextInput
            style={styles.input}
            value={query}
            onChangeText={onQuery}
            placeholder="채팅방 이름·대화 내용 검색"
            placeholderTextColor={colors.placeholder}
            accessibilityLabel="채팅 검색"
            maxLength={100}
            autoFocus
          />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.md },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { ...font.page, color: colors.text },
  buttons: { flexDirection: "row", marginRight: SETTINGS_EDGE_GAP - spacing.xl, transform: [{ translateY: -SETTINGS_RAISE }] },
  search: {
    height: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: 22,
    backgroundColor: colors.surface,
  },
  input: { flex: 1, minWidth: 0, ...font.body, color: colors.text, paddingVertical: 0 },
});
