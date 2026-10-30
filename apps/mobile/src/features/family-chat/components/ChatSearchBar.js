import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import { colors, font, radius, spacing } from "@/theme";

import { SEARCH_MAX_QUERY, searchPositionLabel } from "../searchUtils";

/**
 * 한 줄 안내 문구: 방 정보 대기·오류, 검색 중, 결과 없음, 더 불러오는 중 등. 위치 문구("3/12")는 결과가 있을 때 따로 보인다.
 * @param {{ blocked: boolean, status: string, items: object[], error: string, loadingMore: boolean, moreError: string }} search
 * @param {{ status: string } | undefined} scope 가족방 id 를 알아내는 상태
 * @returns {string}
 */
function statusText(search, scope) {
  if (search.blocked) return scope?.status === "error" ? "대화방 정보를 불러오지 못해 검색할 수 없어요" : "대화방 정보를 불러오는 중이에요";
  if (search.status === "loading") return "검색 중…";
  if (search.status === "error") return search.error;
  if (search.status === "ready" && search.items.length === 0) return "일치하는 대화가 없어요";
  if (search.moreError) return search.moreError;
  if (search.loadingMore) return "더 불러오는 중…";
  return "";
}

/**
 * 채팅방 상단 검색 바(카톡 방식): 닫기, 입력칸, 지우기. 검색어가 있으면 아래 줄에 안내 문구와 현재 위치("n/m", 서버에 더 있으면 "n/m+"), 더 오래된 일치(▲)·더 최근 일치(▼) 버튼이 보인다. 입력은 100자까지.
 * 키보드의 검색 키는 ▲ 와 같다(더 오래된 일치로).
 * @param {{ search: ReturnType<typeof import("../useChatSearch").default>, scope?: { status: string, retry: () => void }, onClose: () => void, placeholder?: string }} props
 */
export default function ChatSearchBar({ search, scope, onClose, placeholder = "대화 내용 검색" }) {
  const { query, setQuery, items, index, hasMore, status } = search;
  const ready = status === "ready" && items.length > 0;
  const canOlder = ready && (index + 1 < items.length || hasMore);
  const canNewer = ready && index > 0;
  const text = statusText(search, scope);
  const retry = search.blocked ? (scope?.status === "error" ? scope.retry : null) : status === "error" ? search.retry : search.moreError ? search.loadMore : null;
  return (
    <View style={styles.wrap}>
      <View style={styles.bar}>
        <IconButton name="chevron-back" label="검색 닫기" onPress={onClose} />
        <View style={styles.field}>
          <Ionicons name="search-outline" size={18} color={colors.textMuted} />
          <TextInput
            style={styles.input}
            value={query}
            onChangeText={setQuery}
            onSubmitEditing={() => search.step("older")}
            placeholder={placeholder}
            placeholderTextColor={colors.placeholder}
            accessibilityLabel="대화 검색어"
            maxLength={SEARCH_MAX_QUERY}
            returnKeyType="search"
            submitBehavior="submit"
            autoCorrect={false}
            autoFocus
          />
          {query ? (
            <Pressable onPress={() => setQuery("")} accessibilityRole="button" accessibilityLabel="검색어 지우기" hitSlop={8}>
              <Ionicons name="close-circle" size={18} color={colors.textMuted} />
            </Pressable>
          ) : null}
        </View>
      </View>
      {query.trim() ? (
        <View style={styles.status}>
          <Text style={styles.statusText} numberOfLines={1} accessibilityLiveRegion="polite">
            {text}
          </Text>
          {retry ? (
            <Pressable onPress={retry} accessibilityRole="button" accessibilityLabel="다시 시도" hitSlop={8}>
              <Text style={styles.retry}>다시 시도</Text>
            </Pressable>
          ) : null}
          {ready ? (
            <>
              <Text style={styles.position} accessibilityLabel={`검색 결과 ${searchPositionLabel(index, items.length, hasMore).replace("/", " 중 ").replace("+", " 이상")}`}>
                {searchPositionLabel(index, items.length, hasMore)}
              </Text>
              <IconButton name="chevron-up" label="더 오래된 일치로" onPress={() => search.step("older")} disabled={!canOlder} />
              <IconButton name="chevron-down" label="더 최근 일치로" onPress={() => search.step("newer")} disabled={!canNewer} />
            </>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { borderBottomWidth: 1, borderBottomColor: colors.divider },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
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
  status: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44, paddingLeft: spacing.lg, paddingRight: spacing.sm },
  statusText: { flex: 1, minWidth: 0, ...font.caption, color: colors.textSub },
  retry: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.accent },
  position: { ...font.caption, fontFamily: font.bodyStrong.fontFamily, color: colors.text },
});
