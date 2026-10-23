import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import { listRecords, originalImageSource } from "../api";
import RecordDetail from "./RecordDetail";

/**
 * 올린 사진·파일 목록(가족 전체가 함께 쓰는 기록). 누르면 상세를 연다.
 * 탭이 보일 때마다 새로 불러와서 방금 올린 것도 바로 나온다. 확인이 필요한 기록은 맨 위에 표시한다.
 * @param {{ active: boolean, focusId?: string | null, onFocusHandled?: () => void, onLoaded?: (items: object[]) => void }} props
 * active: 이 탭이 지금 화면에 보이는지 / focusId: 불러온 뒤 바로 상세를 열 기록 / onLoaded: 목록을 새로 불러올 때마다 알린다
 */
export default function RecordsList({ active, focusId = null, onFocusHandled, onLoaded }) {
  const [items, setItems] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const list = await listRecords();
      setItems(list);
      onLoaded?.(list);
      return list;
    } catch (e) {
      setItems([]);
      setError(e?.message || "기록을 불러오지 못했어요.");
      return [];
    }
  }, [onLoaded]);

  useEffect(() => {
    if (active) refresh();
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!focusId || !items) return;
    const found = items.find((r) => r.id === focusId);
    if (found) setSelected(found);
    onFocusHandled?.();
  }, [focusId, items]); // eslint-disable-line react-hooks/exhaustive-deps

  if (items === null) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  const waiting = items.filter((r) => r.needs_review).length;

  return (
    <View style={styles.flex}>
      <FlatList
        data={items}
        keyExtractor={(r) => r.id}
        onRefresh={refresh}
        refreshing={false}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          waiting > 0 ? (
            <View style={styles.banner}>
              <Ionicons name="alert-circle-outline" size={16} color={colors.warning} />
              <Text style={styles.bannerText}>확인이 필요한 기록이 {waiting}건 있어요. 눌러서 원본과 비교해 주세요.</Text>
            </View>
          ) : null
        }
        ListEmptyComponent={
          <Text style={styles.empty}>{error || "아직 올린 기록이 없어요. 채팅의 + 버튼으로 사진이나 파일을 올려 보세요."}</Text>
        }
        renderItem={({ item }) => {
          const thumb = item.hasOriginal ? originalImageSource(item.id) : null;
          return (
            <Pressable onPress={() => setSelected(item)} accessibilityRole="button" style={[styles.row, item.needs_review && styles.rowReview]}>
              <View style={styles.thumb}>
                {thumb ? (
                  <Image source={thumb} style={styles.thumbImg} contentFit="cover" recyclingKey={item.id} />
                ) : (
                  <Ionicons name="document-text-outline" size={22} color={colors.textMuted} />
                )}
              </View>
              <View style={styles.text}>
                <Text style={styles.title} numberOfLines={1}>
                  {item.title}
                </Text>
                <Text style={styles.meta} numberOfLines={1}>
                  {[item.kind_label, item.occurred_on].filter(Boolean).join(" · ")}
                </Text>
              </View>
              {item.needs_review ? (
                <View style={styles.tag}>
                  <Text style={styles.tagText}>확인 필요</Text>
                </View>
              ) : null}
            </Pressable>
          );
        }}
      />
      <RecordDetail record={selected} onClose={() => setSelected(null)} onChanged={refresh} />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  list: { paddingHorizontal: 8, paddingBottom: 16 },
  banner: { flexDirection: "row", gap: 6, marginHorizontal: 6, marginBottom: 8, padding: 10, borderRadius: 12, backgroundColor: colors.honeySoft },
  bannerText: { flex: 1, fontSize: 12, lineHeight: 18, color: colors.text },
  empty: { paddingHorizontal: 16, paddingTop: 16, fontSize: 13, lineHeight: 20, color: colors.textMuted },
  row: { minHeight: 60, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 12, flexDirection: "row", alignItems: "center", gap: 10 },
  rowReview: { backgroundColor: colors.peachSoft },
  thumb: { width: 46, height: 46, borderRadius: 10, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  thumbImg: { width: "100%", height: "100%" },
  text: { flex: 1, minWidth: 0, gap: 2 },
  title: { fontSize: 15, color: colors.text },
  meta: { fontSize: 12, color: colors.textMuted },
  tag: { paddingHorizontal: 8, height: 22, borderRadius: 11, backgroundColor: colors.peach, alignItems: "center", justifyContent: "center" },
  tagText: { fontSize: 11, fontWeight: "700", color: colors.text },
});
