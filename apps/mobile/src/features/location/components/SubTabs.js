import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font } from "@/theme";

/**
 * 위치 탭 안의 아이콘 하위 탭(내 위치·이동 기록·여행 모드·설정).
 * @param {{ tabs: { key: string, label: string, icon: string }[], value: string, onChange: (key: string) => void }} props
 */
export default function SubTabs({ tabs, value, onChange }) {
  return (
    <View style={styles.bar} accessibilityRole="tablist">
      {tabs.map((t) => {
        const active = t.key === value;
        return (
          <Pressable
            key={t.key}
            onPress={() => onChange(t.key)}
            accessibilityRole="tab"
            accessibilityLabel={t.label}
            aria-selected={active}
            style={[styles.item, active && styles.itemActive]}
            testID={`location-tab-${t.key}`}
          >
            <Ionicons name={active ? t.icon : `${t.icon}-outline`} size={22} color={active ? colors.text : colors.textMuted} />
            <Text style={[styles.label, active && styles.labelActive]}>{t.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: "row", backgroundColor: colors.surface, borderRadius: 16, padding: 4 },
  item: { flex: 1, minHeight: 56, borderRadius: 12, alignItems: "center", justifyContent: "center", gap: 2 },
  itemActive: { backgroundColor: colors.card },
  label: { ...font.caption, fontSize: 12, color: colors.textMuted },
  labelActive: { fontWeight: "700", color: colors.text },
});
