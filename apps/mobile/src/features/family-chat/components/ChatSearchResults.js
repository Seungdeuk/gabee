import { ActivityIndicator, FlatList, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

import { resultCountLabel } from "../searchUtils";
import SearchResultRow from "./SearchResultRow";

/**
 * 채팅방 안 검색 결과 목록(최신순). 결과 개수, 끝에 닿으면 다음 쪽 자동 불러오기, 로딩·없음·오류 상태를 보여 준다.
 * 한 방 안 검색인데 그 방의 id 를 아직 모르면(search.blocked) 검색하지 않고 안내만 보인다.
 * @param {{ search: ReturnType<typeof import("../useChatSearch").default>, onPick: (item: object) => void, scope?: { status: string, retry: () => void } }} props
 */
export default function ChatSearchResults({ search, onPick, scope }) {
  const { status, items, terms, hasMore, loadingMore, moreError } = search;

  if (search.blocked) {
    return scope?.status === "error" ? (
      <View style={styles.center} accessibilityRole="alert">
        <Text style={styles.hint}>대화방 정보를 불러오지 못해 검색할 수 없어요</Text>
        <Button label="다시 시도" small onPress={scope.retry} />
      </View>
    ) : (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="대화방 정보를 불러오는 중" />
        <Text style={styles.hint}>대화방 정보를 불러오는 중이에요</Text>
      </View>
    );
  }

  if (status === "idle") {
    return (
      <View style={styles.center}>
        <Text style={styles.hint}>찾을 글자를 입력해 주세요</Text>
      </View>
    );
  }
  if (status === "loading") {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} accessibilityLabel="검색 중" />
      </View>
    );
  }
  if (status === "error") {
    return (
      <View style={styles.center} accessibilityRole="alert">
        <Text style={styles.hint}>{search.error}</Text>
        <Button label="다시 시도" small onPress={search.retry} />
      </View>
    );
  }
  if (items.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.hint}>검색 결과가 없어요</Text>
      </View>
    );
  }
  return (
    <FlatList
      style={styles.list}
      data={items}
      keyExtractor={(it) => String(it.id)}
      renderItem={({ item }) => <SearchResultRow item={item} terms={terms} onPress={() => onPick(item)} />}
      ListHeaderComponent={
        <Text style={styles.count} accessibilityLiveRegion="polite">
          {`검색 결과 ${resultCountLabel(items.length, hasMore)}`}
        </Text>
      }
      ListFooterComponent={
        loadingMore ? (
          <ActivityIndicator style={styles.footer} color={colors.accent} accessibilityLabel="더 불러오는 중" />
        ) : moreError ? (
          <View style={styles.footer}>
            <Text style={styles.hint}>{moreError}</Text>
            <Button label="다시 시도" small onPress={search.loadMore} />
          </View>
        ) : hasMore ? (
          <View style={styles.footer}>
            <Button label="더 보기" small onPress={search.loadMore} />
          </View>
        ) : null
      }
      onEndReached={() => {
        if (!moreError) search.loadMore();
      }}
      onEndReachedThreshold={0.4}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
    />
  );
}

const styles = StyleSheet.create({
  list: { flex: 1, backgroundColor: colors.background },
  content: { paddingHorizontal: spacing.md, paddingBottom: spacing.xxl },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xxl },
  hint: { ...font.body, color: colors.textSub, textAlign: "center" },
  count: { ...font.caption, color: colors.textMuted, paddingHorizontal: spacing.sm, paddingVertical: spacing.sm },
  footer: { alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md },
});
