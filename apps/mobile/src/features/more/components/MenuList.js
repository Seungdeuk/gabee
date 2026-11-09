import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Card from "@/shared/components/Card";
import Tag from "@/shared/components/Tag";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 마이 페이지 세로 목록: 묶음마다 제목과 둥근 카드가 있고, 카드 안 줄에는 둥근 아이콘·이름·화살표만 보인다(설명은 접근성 읽기에만 쓴다).
 * 줄 사이에는 얇은 구분선이 있고 준비 중 항목은 흐리게 보인다. badge 가 있으면 오른쪽에 작은 태그로, value 가 있으면 글자로 보이고, static 줄은 화살표가 없다(환경설정 화면도 이 목록을 쓴다).
 * @param {{ sections: { key: string, title: string, items: { key: string, icon: string, title: string, subtitle: string, soon?: boolean, badge?: string, value?: string, static?: boolean }[] }[], onPressItem: (item: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function MenuList({ sections, onPressItem }) {
  return (
    <View style={styles.sections}>
      {sections.map((section) => (
        <View key={section.key} style={styles.section}>
          <Text style={styles.sectionTitle} accessibilityRole="header">
            {section.title}
          </Text>
          <Card tone="white" style={styles.card}>
            {section.items.map((item, index) => (
              <Pressable
                key={item.key}
                testID={`menu-${item.key}`}
                style={[styles.row, index > 0 ? styles.divider : null, item.soon ? styles.soon : null]}
                onPress={() => onPressItem(item)}
                accessibilityRole="button"
                accessibilityLabel={[item.title, item.subtitle, item.badge, item.value].filter(Boolean).join(", ")}
                accessibilityHint={item.soon ? "준비 중이에요" : undefined}
              >
                <View style={styles.chip}>
                  <Ionicons name={item.icon} size={18} color={colors.accent} />
                </View>
                <Text style={styles.title}>{item.title}</Text>
                {item.badge ? (
                  <View>
                    <Tag label={item.badge} tone="orange" />
                  </View>
                ) : null}
                {item.value ? <Text style={styles.value}>{item.value}</Text> : null}
                {item.static ? null : <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />}
              </Pressable>
            ))}
          </Card>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  sections: { gap: spacing.lg },
  section: { gap: spacing.sm },
  sectionTitle: { ...font.bodyStrong, color: colors.text },
  card: { gap: 0, paddingVertical: spacing.xs, paddingHorizontal: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 52 },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.divider },
  chip: { width: 34, height: 34, borderRadius: radius.pill, backgroundColor: colors.peachSoft, alignItems: "center", justifyContent: "center" },
  soon: { opacity: 0.6 },
  title: { ...font.body, color: colors.text, flex: 1 },
  value: { ...font.caption, color: colors.textSub },
});
