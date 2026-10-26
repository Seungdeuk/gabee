import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

import { resultCountLabel } from "../searchUtils";
import SearchResultRow from "./SearchResultRow";

/**
 * 소통 탭 검색의 "대화 내용" 섹션: 서버 검색 결과를 방 이름과 함께 보여 준다. 누르면 그 방의 해당 메시지 위치로 이동한다.
 * @param {{ search: ReturnType<typeof import("../useChatSearch").default>, roomLabel: (item: object) => string, onPick: (item: object) => void }} props
 */
export default function ContentSearchSection({ search, roomLabel, onPick }) {
  const { status, items, terms, hasMore, loadingMore, moreError } = search;
  if (status === "idle") return null;
  return (
    <View style={styles.wrap}>
      <View style={styles.head}>
        <Text style={styles.title} accessibilityRole="header">
          대화 내용
        </Text>
        {status === "ready" && items.length > 0 ? <Text style={styles.count}>{resultCountLabel(items.length, hasMore)}</Text> : null}
      </View>
      {status === "loading" ? <ActivityIndicator style={styles.pad} color={colors.accent} accessibilityLabel="대화 내용을 찾는 중" /> : null}
      {status === "error" ? (
        <View style={styles.pad} accessibilityRole="alert">
          <Text style={styles.hint}>{search.error}</Text>
          <Button label="다시 시도" small onPress={search.retry} />
        </View>
      ) : null}
      {status === "ready" && items.length === 0 ? <Text style={[styles.hint, styles.pad]}>대화 내용에서는 찾지 못했어요</Text> : null}
      {status === "ready"
        ? items.map((item) => <SearchResultRow key={item.id} item={item} terms={terms} roomLabel={roomLabel(item)} onPress={() => onPick(item)} />)
        : null}
      {status === "ready" && loadingMore ? <ActivityIndicator style={styles.pad} color={colors.accent} accessibilityLabel="더 불러오는 중" /> : null}
      {status === "ready" && moreError ? (
        <View style={styles.pad}>
          <Text style={styles.hint}>{moreError}</Text>
          <Button label="다시 시도" small onPress={search.loadMore} />
        </View>
      ) : null}
      {status === "ready" && hasMore && !loadingMore && !moreError ? (
        <View style={styles.pad}>
          <Button label="더 보기" small onPress={search.loadMore} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  head: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", paddingHorizontal: spacing.sm },
  title: { ...font.section, color: colors.text },
  count: { ...font.caption, color: colors.textMuted },
  pad: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md },
  hint: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
