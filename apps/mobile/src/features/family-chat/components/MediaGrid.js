import { useMemo } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import AuthImage from "@/shared/components/AuthImage";
import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

import { GRID_COLUMNS, buildGridItems, emptyMediaText, thumbPath } from "../mediaUtils";

const GAP = 2;

/**
 * 모음 격자(3열 정사각 썸네일, 월별 구분 헤더). 아래로 내려가면 onEndReached 로 다음 쪽을 부른다.
 * 로딩·오류("다시 시도")·빈 상태는 종류(kind)별 문구로 보인다.
 * @param {{ kind: string, items: object[], status: "loading" | "ready" | "error", error: string, loadingMore: boolean, hasMore: boolean, width: number, onEndReached: () => void, onRetry: () => void, onOpen: (item: object) => void }} props width: 격자가 차지하는 너비
 */
export default function MediaGrid({ kind, items, status, error, loadingMore, hasMore, width, onEndReached, onRetry, onOpen }) {
  const data = useMemo(() => buildGridItems(items), [items]);
  if (status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="불러오는 중" />
      </View>
    );
  }
  if (status === "error") {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{error}</Text>
        <Button label="다시 시도" onPress={onRetry} />
      </View>
    );
  }
  if (items.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyText}>{emptyMediaText(kind)}</Text>
      </View>
    );
  }
  const cell = Math.floor((width - GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS);
  return (
    <FlatList
      data={data}
      keyExtractor={(it) => it.key}
      renderItem={({ item }) =>
        item.type === "header" ? (
          <Text style={styles.header} accessibilityRole="header">
            {item.label}
          </Text>
        ) : (
          <View style={styles.row}>
            {item.items.map((photo) => (
              <Pressable key={photo.attachment_id} onPress={() => onOpen(photo)} accessibilityRole="imagebutton" accessibilityLabel={`${photo.user_name ?? "가족"}님이 보낸 사진, 누르면 크게 봐요`}>
                <AuthImage path={thumbPath(photo)} style={{ width: cell, height: cell }} />
              </Pressable>
            ))}
          </View>
        )
      }
      onEndReached={() => {
        if (hasMore && !error) onEndReached();
      }}
      onEndReachedThreshold={0.6}
      ListFooterComponent={
        loadingMore ? (
          <ActivityIndicator style={styles.footer} color={colors.accent} accessibilityLabel="더 불러오는 중" />
        ) : error ? (
          <View style={styles.footer}>
            <Text style={styles.emptyText}>{error}</Text>
            <Button label="다시 시도" onPress={onEndReached} />
          </View>
        ) : null
      }
    />
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  emptyText: { ...font.body, color: colors.textSub, textAlign: "center" },
  header: { ...font.bodyStrong, color: colors.text, paddingHorizontal: spacing.lg, paddingTop: spacing.lg, paddingBottom: spacing.sm },
  row: { flexDirection: "row", gap: GAP, marginBottom: GAP },
  footer: { alignItems: "center", gap: spacing.sm, padding: spacing.lg },
});
