import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

import { DAY_CHIPS, hasCandidateDay } from "../togetherUtils";
import ChipRow from "./ChipRow";

/**
 * AI 가 찾은 할 일 후보 한 줄과 "함께하기로 보내기" 버튼. 사용자가 눌러야만 보내진다(AI 가 직접 보내지 않는다).
 * 후보에 날짜가 없으면 날짜 칩(오늘·내일·3일 뒤·1주일 뒤)을 먼저 골라야 한다(함께하기는 날짜가 필수다).
 * @param {{ candidate: { title: string, assignee_name?: string | null, due?: string | null }, state: undefined | "sending" | "ok" | string, day: string | null, onPickDay: (key: string) => void, onRegister: () => void, testID?: string }} props state 는 보낸 결과(없음/"sending"/"ok"/오류 문구), day 는 고른 날짜 칩 key
 */
export default function TodoCandidateRow({ candidate, state, day, onPickDay, onRegister, testID }) {
  const needDay = !hasCandidateDay(candidate);
  const detail = [candidate.assignee_name && `담당 ${candidate.assignee_name}`, candidate.due && `기한 ${candidate.due}`].filter(Boolean).join(" · ");
  return (
    <View style={styles.candidate}>
      <Text style={styles.title}>{candidate.title}</Text>
      <Text style={styles.caption}>{detail || "담당자·기한이 정해지지 않았어요"}</Text>
      {state === "ok" ? (
        <Text style={styles.success}>함께하기로 보냈어요</Text>
      ) : (
        <>
          {needDay ? <ChipRow label="날짜" options={DAY_CHIPS} value={day} onChange={onPickDay} /> : null}
          {state && state !== "sending" ? (
            <Text style={styles.error} accessibilityRole="alert">
              {state}
            </Text>
          ) : null}
          <Button label={state === "sending" ? "보내는 중..." : "함께하기로 보내기"} small variant="secondary" onPress={onRegister} disabled={state === "sending"} testID={testID} />
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
