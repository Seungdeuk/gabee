import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

/**
 * AI 가 찾은 할 일 후보 한 줄과 "할 일로 등록" 버튼. 사용자가 눌러야만 등록된다(AI 가 직접 등록하지 않는다).
 * @param {{ candidate: { title: string, assignee_name?: string | null, due?: string | null }, state: undefined | "sending" | "ok" | string, onRegister: () => void, testID?: string }} props state 는 등록 결과(없음/"sending"/"ok"/오류 문구)
 */
export default function TodoCandidateRow({ candidate, state, onRegister, testID }) {
  const detail = [candidate.assignee_name && `담당 ${candidate.assignee_name}`, candidate.due && `기한 ${candidate.due}`].filter(Boolean).join(" · ");
  return (
    <View style={styles.candidate}>
      <Text style={styles.title}>{candidate.title}</Text>
      <Text style={styles.caption}>{detail || "담당자·기한이 정해지지 않았어요"}</Text>
      {state === "ok" ? (
        <Text style={styles.success}>할 일로 등록했어요</Text>
      ) : (
        <>
          {state && state !== "sending" ? (
            <Text style={styles.error} accessibilityRole="alert">
              {state}
            </Text>
          ) : null}
          <Button label={state === "sending" ? "등록하는 중..." : "할 일로 등록"} small variant="secondary" onPress={onRegister} disabled={state === "sending"} testID={testID} />
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  candidate: { gap: spacing.xs, paddingVertical: spacing.xs },
  title: { ...font.bodyStrong, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
  success: { ...font.caption, color: colors.success },
  error: { ...font.body, color: colors.danger },
});
