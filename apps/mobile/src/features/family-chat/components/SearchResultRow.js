import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { formatSearchTime, previewSnippet } from "../searchUtils";
import Highlighted from "./Highlighted";

/**
 * 검색 결과 한 줄: (소통 탭에서는 방 이름), 보낸 사람, 시각, 두 줄 이내 미리보기(검색어 굵게). 누르면 그 메시지 위치로 이동한다.
 * @param {{ item: { id: number, user_name: string, text: string, created_at: string }, terms: string[], roomLabel?: string, onPress: () => void, now?: Date }} props
 */
export default function SearchResultRow({ item, terms, roomLabel, onPress, now }) {
  const time = formatSearchTime(item.created_at, now);
  const snippet = previewSnippet(item.text, terms);
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`${roomLabel ? `${roomLabel}, ` : ""}${item.user_name}, ${time}, ${snippet}. 누르면 그 대화로 이동해요`}
      style={({ pressed }) => [styles.row, pressed && styles.pressed]}
    >
      <View style={styles.head}>
        <Text style={styles.name} numberOfLines={1}>
          {roomLabel ? `${roomLabel} · ${item.user_name}` : item.user_name}
        </Text>
        <Text style={styles.time}>{time}</Text>
      </View>
      <Highlighted text={snippet} terms={terms} style={styles.text} numberOfLines={2} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: 64, gap: spacing.xs, paddingVertical: spacing.md, paddingHorizontal: spacing.sm, borderRadius: radius.lg },
  pressed: { backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  name: { flex: 1, minWidth: 0, ...font.bodyStrong, color: colors.textSub },
  time: { ...font.tab, color: colors.textMuted },
  text: { ...font.body, color: colors.text },
});
