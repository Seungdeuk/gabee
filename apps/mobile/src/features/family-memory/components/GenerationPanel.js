import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { GENERATION_LABELS, generationView } from "../generation";

/**
 * "추억 만들기" 패널(PR10). 서버가 알려 준 진행 상태(동의 필요·사진 부족·처리 중·완료·실패)를 구분해 보여 주고, 누를 수 있을 때만 버튼을 낸다.
 * 서버 입구가 꺼져 있으면(hidden) 아무것도 그리지 않는다. 사진·인물 정보는 개수만 쓴다.
 * @param {{ state: object, polling: boolean, onStart: () => void }} props
 */
export default function GenerationPanel({ state, polling, onStart }) {
  if (state.hidden) return null;
  const view = generationView(state.gen, { polling, busy: state.busy });
  if (!view.visible && !state.error) return null;
  return (
    <View style={styles.panel} accessibilityRole="summary">
      {view.visible ? (
        <View style={styles.row}>
          {view.spinner ? <ActivityIndicator color={colors.accent} accessibilityLabel="진행 중" /> : null}
          <Text style={styles.text}>{view.text}</Text>
        </View>
      ) : null}
      {state.error ? <Text style={styles.error}>{state.error}</Text> : null}
      {view.button ? <Button label={GENERATION_LABELS[view.button]} onPress={onStart} small /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { marginHorizontal: spacing.lg, marginTop: spacing.md, padding: spacing.md, gap: spacing.sm, borderRadius: radius.md, backgroundColor: colors.honeySoft },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  text: { ...font.caption, color: colors.text, flex: 1 },
  error: { ...font.caption, color: colors.textSub },
});