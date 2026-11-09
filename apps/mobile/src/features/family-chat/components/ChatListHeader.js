import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, TextInput, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import { SETTINGS_EDGE_GAP, SETTINGS_RAISE } from "@/shared/components/SettingsButton";
import { colors, font, spacing } from "@/theme";

/**
 * 소통 탭 상단: 큰 제목 "우리 도란도란", 오른쪽 새 대화 버튼과 맨 오른쪽 알림 종(bell, 라우트에서 조립), 그 아래 항상 보이는 검색창.
 * 검색 입력은 방 이름과 대화 내용을 함께 찾는다(대화 내용 결과는 화면이 입력값으로 따로 불러와 보여 준다).
 * 새 대화·알림 버튼 줄은 제목 줄 높이와 상관없이 다른 탭과 같은 자리(화면 오른쪽 끝에서 6, 상단바 높이 56 의 세로 가운데)에 고정한다.
 * @param {{ query: string, onQuery: (text: string) => void, onNew: () => void, bell?: import("react").ReactNode }} props
 */
export default function ChatListHeader({ query, onQuery, onNew, bell = null }) {
  return (
    <View style={styles.wrap}>
      <View style={styles.top}>
        <Text style={styles.title} accessibilityRole="header">
          우리 도란도란
        </Text>
        <View style={styles.buttons}>
          <IconButton name="add" label="새 대화" onPress={onNew} />
          {bell}
        </View>
      </View>
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
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.md },
  top: { justifyContent: "center" },
  title: { ...font.page, color: colors.text },
  // 제목 줄 높이에 따라 버튼이 따라 내려가지 않게 절대 위치로 둔다(화면 안쪽 여백만큼 밖으로 내어 오른쪽 끝 6 에 맞춘다)
  buttons: { position: "absolute", top: -SETTINGS_RAISE, right: SETTINGS_EDGE_GAP - spacing.xl, flexDirection: "row" },
  search: {
    height: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: 22,
    backgroundColor: colors.surface,
  },
  // 입력창은 줄 높이를 글자 크기에 맞춘다: font.body 의 줄 높이(24)를 그대로 쓰면 안드로이드에서 글자가 위로 밀려 올라간다
  input: { flex: 1, minWidth: 0, height: 44, ...font.body, lineHeight: 18, includeFontPadding: false, textAlignVertical: "center", color: colors.text, paddingVertical: 0 },
});
