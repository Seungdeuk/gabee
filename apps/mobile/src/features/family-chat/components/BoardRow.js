import { Pressable, StyleSheet, Text, View } from "react-native";

import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

import { boardA11y, boardAuthor, boardMeta, boardPreview } from "../boardUtils";

/**
 * 게시판 목록의 카드 한 장: 본문 앞부분, 올린 사람·시각, "현재 공지"/"원본 삭제됨" 표시. 누르면 전체 내용(상세)을 연다.
 * @param {{ item: object, nameOf?: (userId: string) => string | undefined, onPress: (item: object) => void }} props
 */
export default function BoardRow({ item, nameOf, onPress }) {
  const author = boardAuthor(item, nameOf);
  return (
    <Pressable onPress={() => onPress(item)} accessibilityRole="button" accessibilityLabel={boardA11y(item, nameOf)} style={({ pressed }) => [styles.card, pressed && styles.pressed]}>
      <View style={styles.tags}>
        {item.is_current ? <Tag label="현재 공지" tone="orange" /> : <Tag label="지난 공지" />}
        {item.message_deleted ? <Tag label="원본 삭제됨" tone="red" /> : null}
      </View>
      <Text style={styles.text} numberOfLines={3}>
        {boardPreview(item)}
      </Text>
      <Text style={styles.meta} numberOfLines={1}>
        {boardMeta(item, nameOf)}
      </Text>
      {author ? (
        <Text style={styles.meta} numberOfLines={1}>
          {author}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.card, borderRadius: radius.card, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, gap: spacing.xs },
  pressed: { backgroundColor: colors.surface },
  tags: { flexDirection: "row", gap: spacing.xs, marginBottom: spacing.xs },
  text: { ...font.body, color: colors.text },
  meta: { ...font.caption, color: colors.textMuted },
});
