import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Tag from "@/shared/components/Tag";
import { colors, font, spacing } from "@/theme";

/**
 * 마이 페이지 세로 목록: 묶음마다 제목이 있고 줄에는 아이콘·이름·화살표만 보인다(설명은 접근성 읽기에만 쓴다).
 * 묶음 사이에는 얇은 구분선이 있고 준비 중 항목은 흐리게 보인다. badge 가 있으면 오른쪽에 작은 태그로 보인다.
 * @param {{ sections: { key: string, title: string, items: { key: string, icon: string, title: string, subtitle: string, soon?: boolean, badge?: string }[] }[], onPressItem: (item: object) => void }} props
 * @returns {import("react").ReactElement}
 */
export default function MenuList({ sections, onPressItem }) {
  return (
    <View>
      {sections.map((section, index) => (
        <View key={section.key} style={[styles.section, index > 0 ? styles.divider : null]}>
          <Text style={styles.sectionTitle} accessibilityRole="header">
            {section.title}
          </Text>
          {section.items.map((item) => (
            <Pressable
              key={item.key}
              testID={`menu-${item.key}`}
              style={[styles.row, item.soon ? styles.soon : null]}
              onPress={() => onPressItem(item)}
              accessibilityRole="button"
              accessibilityLabel={[item.title, item.subtitle, item.badge].filter(Boolean).join(", ")}
              accessibilityHint={item.soon ? "준비 중이에요" : undefined}
            >
              <Ionicons name={item.icon} size={20} color={colors.text} />
              <Text style={styles.title}>{item.title}</Text>
              {item.badge ? (
                <View>
                  <Tag label={item.badge} tone="orange" />
                </View>
              ) : null}
              <Ionicons name="chevron-forward" size={20} color={colors.textMuted} />
            </Pressable>
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { paddingVertical: spacing.sm },
  divider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.divider, marginTop: spacing.sm },
  sectionTitle: { ...font.bodyStrong, color: colors.text, paddingVertical: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, minHeight: 48 },
  soon: { opacity: 0.6 },
  title: { ...font.body, color: colors.text, flex: 1 },
});
