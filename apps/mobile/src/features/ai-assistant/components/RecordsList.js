import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import { listRecords, originalImageSource } from "../api";
import RecordDetail from "./RecordDetail";

/**
 * 올린 사진·파일 목록(가족 전체가 함께 쓰는 기록). 누르면 상세를 연다.
 * 탭이 보일 때마다 새로 불러와서 방금 올린 것도 바로 나온다.
 * @param {{ active: boolean }} props active: 이 탭이 지금 화면에 보이는지
 */
export default function RecordsList({ active }) {
  const [items, setItems] = useState(null); // null: 불러오는 중
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  const refresh = useCallback(async () => {
    setError("");
    try {
      setItems(await listRecords());
    } catch (e) {
      setItems([]);
      setError(e?.message || "기록을 불러오지 못했어요.");
    }
  }, []);

  useEffect(() => {
    if (active) refresh();
  }, [active, refresh]);

  if (items === null) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <FlatList
        data={items}
        keyExtractor={(r) => r.id}
        onRefresh={refresh}
        refreshing={false}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>{error || "아직 올린 기록이 없어요. 채팅의 + 버튼으로 사진이나 파일을 올려 보세요."}</Text>
        }
        renderItem={({ item }) => {
          const thumb = item.hasOriginal ? originalImageSource(item.id) : null;
          return (
            <Pressable onPress={() => setSelected(item)} accessibilityRole="button" style={styles.row}>
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
              {item.has_unread_parts ? <Ionicons name="alert-circle-outline" size={18} color={colors.warning} /> : null}
            </Pressable>
          );
        }}
      />
      <RecordDetail record={selected} onClose={() => setSelected(null)} />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  list: { paddingHorizontal: 8, paddingBottom: 16 },
  empty: { paddingHorizontal: 16, paddingTop: 16, fontSize: 13, lineHeight: 20, color: colors.textMuted },
  row: { minHeight: 60, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 12, flexDirection: "row", alignItems: "center", gap: 10 },
  thumb: { width: 46, height: 46, borderRadius: 10, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  thumbImg: { width: "100%", height: "100%" },
  text: { flex: 1, minWidth: 0, gap: 2 },
  title: { fontSize: 15, color: colors.text },
  meta: { fontSize: 12, color: colors.textMuted },
});
