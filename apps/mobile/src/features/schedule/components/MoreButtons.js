import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "@/theme";

import { PAGE_SIZE } from "../upcoming";

/**
 * 목록 아래 "5개 더보기" / "접기" 버튼. 남은 것이 있으면 "N개 더보기"(최대 5)가 나오고, 한 번이라도 펼쳤으면 "접기"가 함께 나와
 * 누르면 처음 상태(맨 처음 5개)로 돌아간다. 남은 것도 없고 펼친 적도 없으면 아무것도 그리지 않는다.
 * @param {{ remaining: number, expanded: boolean, onMore: () => void, onFold: () => void }} props
 */
export default function MoreButtons({ remaining, expanded, onMore, onFold }) {
  if (remaining <= 0 && !expanded) return null;
  return (
    <View style={styles.row}>
      {remaining > 0 ? (
        <Pressable onPress={onMore} style={styles.button} accessibilityRole="button">
          <Text style={styles.text}>{`${Math.min(PAGE_SIZE, remaining)}개 더보기`}</Text>
        </Pressable>
      ) : null}
      {expanded ? (
        <Pressable onPress={onFold} style={styles.button} accessibilityRole="button" accessibilityLabel="접기, 처음 상태로">
          <Text style={styles.text}>접기</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.sm },
  button: {
    flex: 1,
    alignItems: "center",
    paddingVertical: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.button,
  },
  text: { fontSize: 14, fontWeight: "500", color: colors.textMuted },
});
