import { StyleSheet, Text, View } from "react-native";

import { colors, spacing } from "@/theme";

import { whoChips } from "../calendar";
import { useHiddenWho } from "../favorites_hook";
import { addTopic, removeTopic, useMembers, useTopics } from "../store";
import TopicChips from "./TopicChips";
import WhoChips from "./WhoChips";

/**
 * 누구 / 주제 필터 칩 두 줄. 안 켜면 전체, 켠 칩을 다시 누르면 해제(여러 개 가능).
 * 일정 등록 화면과 같은 칩이라 길게 눌러 줄에서 빼고("삭제"), "+ 누구"로 다시 넣고, "+ 주제"로 새 주제를 만들 수 있다.
 * 누구 칩은 나·가족·부모님이고, 뺀 목록은 이 화면 전용으로 이 폰에만 저장한다. 주제를 지우면 그 주제 필터도 풀린다.
 * @param {{ filter: { whoIds: string[], topicIds: string[] }, onToggleWho: (id: string) => void, onToggleTopic: (id: string) => void }} props
 */
export default function FilterRows({ filter, onToggleWho, onToggleTopic }) {
  const family = useMembers();
  const topics = useTopics();
  const chips = whoChips(family).map((chip) => ({ id: chip.id, name: chip.label }));
  const who = useHiddenWho("filter", chips);

  const hideWho = (id) => {
    who.hide(id);
    if (filter.whoIds.includes(id)) onToggleWho(id);
  };
  const deleteTopic = (id) => {
    removeTopic(id);
    if (filter.topicIds.includes(id)) onToggleTopic(id);
  };

  return (
    <View style={styles.rows}>
      <View style={styles.row}>
        <Text style={styles.label}>누구</Text>
        <View style={styles.chips}>
          <WhoChips
            members={chips}
            hiddenIds={who.hidden}
            selectedIds={filter.whoIds}
            onToggle={onToggleWho}
            onHide={hideWho}
            onShow={who.show}
          />
        </View>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>주제</Text>
        <View style={styles.chips}>
          <TopicChips
            topics={topics}
            selectedIds={filter.topicIds}
            onToggle={onToggleTopic}
            onCreate={addTopic}
            onDelete={deleteTopic}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  rows: { gap: spacing.xs },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  label: { width: 30, fontSize: 13, color: colors.textMuted, paddingTop: 5 },
  chips: { flex: 1 },
});
