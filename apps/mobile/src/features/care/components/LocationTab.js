import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import useResource from "@/shared/hooks/useResource";
import { colors, font } from "@/theme";

import { getLocation } from "../api";

/** 위치 확인: 이번 단계에서는 실제 GPS 없이 예시 위치만 보여 준다. 예시라는 표시를 분명히 한다. */
export default function LocationTab() {
  const { data, error, loading } = useResource(getLocation);

  if (loading && !data) return <Text style={styles.muted}>불러오는 중…</Text>;
  if (!data) return <Text style={styles.error}>{error || "위치를 불러오지 못했어요"}</Text>;

  return (
    <View style={styles.wrap}>
      <Card tone="orange">
        <Text style={styles.notice} testID="location-notice">
          예시 화면 · {data.notice}
        </Text>
      </Card>
      <Card tone="white">
        <View style={styles.head}>
          <View style={styles.grow}>
            <Text style={styles.place}>{data.place}</Text>
            <Text style={styles.caption}>
              {data.lat}, {data.lng}
            </Text>
          </View>
          <Tag label="예시" tone="orange" />
        </View>
        <View style={styles.map}>
          <Ionicons name="location-outline" size={28} color={colors.textMuted} />
          <Text style={styles.caption}>지도 없음 · 예시 위치</Text>
        </View>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 16 },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  grow: { flex: 1, gap: 2 },
  place: { ...font.cardTitle, color: colors.text },
  notice: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  map: {
    height: 150,
    borderRadius: 16,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  muted: { ...font.caption, color: colors.textMuted, textAlign: "center", paddingVertical: 16 },
  error: { ...font.body, color: colors.danger },
});
