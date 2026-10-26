import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { SEARCH_MAX_QUERY } from "../searchUtils";

/**
 * 채팅방 상단 검색 바: 닫기(뒤로), 입력칸, 지우기. 입력은 100자까지.
 * @param {{ value: string, onChange: (text: string) => void, onClose: () => void, placeholder?: string }} props
 */
export default function ChatSearchBar({ value, onChange, onClose, placeholder = "대화 내용 검색" }) {
  return (
    <View style={styles.bar}>
      <IconButton name="chevron-back" label="검색 닫기" onPress={onClose} />
      <View style={styles.field}>
        <Ionicons name="search-outline" size={18} color={colors.textMuted} />
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChange}
          placeholder={placeholder}
          placeholderTextColor={colors.placeholder}
          accessibilityLabel="대화 검색어"
          maxLength={SEARCH_MAX_QUERY}
          returnKeyType="search"
          autoCorrect={false}
          autoFocus
        />
        {value ? (
          <Pressable onPress={() => onChange("")} accessibilityRole="button" accessibilityLabel="검색어 지우기" hitSlop={8}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  field: {
    flex: 1,
    minWidth: 0,
    height: 40,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    marginRight: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  input: { flex: 1, minWidth: 0, ...font.body, color: colors.text, paddingVertical: 0 },
});
