import { ScrollView, StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "@/theme";

import { whoChips } from "../calendar";
import { members, topics } from "../mock";
import FilterChip from "./FilterChip";

/**
 * 누구 / 주제 칩 두 줄(가로 스크롤). 안 켜면 전체, 켠 칩을 다시 누르면 해제.
 * "+ 누구"·"+ 주제" 추가와 꾹 눌러 수정은 이후 PR에서 연결한다.
 * @param {{ filter: { whoIds: string[], topicIds: string[] }, onToggleWho: (id: string) => void, onToggleTopic: (id: string) => void }} props
 */
export default function FilterRows({ filter, onToggleWho, onToggleTopic }) {
  return (
    <View style={styles.rows}>
      <View style={styles.row}>
        <Text style={styles.label}>누구</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {whoChips(members).map((chip) => (
            <FilterChip
              key={chip.id}
              label={chip.label}
              selected={filter.whoIds.includes(chip.id)}
              onPress={() => onToggleWho(chip.id)}
            />
          ))}
          <FilterChip label="+ 누구" muted />
        </ScrollView>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>주제</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {topics.map((topic) => (
            <FilterChip
              key={topic.id}
              label={topic.name}
              selected={filter.topicIds.includes(topic.id)}
              onPress={() => onToggleTopic(topic.id)}
            />
          ))}
          <FilterChip label="+ 주제" muted />
        </ScrollView>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  rows: { gap: spacing.xs },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  label: { width: 30, fontSize: 13, color: colors.textMuted },
  chips: { flexDirection: "row", gap: 6, paddingVertical: 1 },
});
