import { StyleSheet, Text, TextInput, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { canRegisterSchedule } from "../messages";
import { completeScheduleCandidate, formatTimeInput, scheduleCandidateNeeds } from "../scheduleCandidateUtils";
import { DAY_CHIPS, formatDayInput } from "../togetherUtils";
import ChipRow from "./ChipRow";

/**
 * AI 가 찾은 일정 후보 한 줄과 "일정으로 등록" 버튼. 후보에 날짜나 시간이 빠져 있으면 그 자리에서 날짜 칩(오늘·내일·직접 입력)과
 * 시간 입력(HH:MM)으로 채울 수 있고, 둘 다 정해지면 바로 등록 버튼이 켜진다. 없는 값은 지어내지 않고 사용자가 정한 값만 쓴다.
 * 사용자가 눌러야만 등록된다(AI 가 직접 등록하지 않는다).
 * @param {{ candidate: { title: string, date?: string | null, time?: string | null, place?: string | null }, state: undefined | "sending" | "ok" | string, day: string | null, customText: string, timeText: string, onPickDay: (key: string) => void, onChangeCustom: (text: string) => void, onChangeTime: (text: string) => void, onRegister: (completed: object) => void, testID?: string }} props
 */
export default function ScheduleCandidateRow({ candidate, state, day, customText = "", timeText = "", onPickDay, onChangeCustom, onChangeTime, onRegister, testID }) {
  const needs = scheduleCandidateNeeds(candidate);
  const completed = completeScheduleCandidate(candidate, { day, customText, timeText });
  const ready = canRegisterSchedule(completed);
  const detail = [completed.date, completed.time, candidate.place].filter(Boolean).join(" · ");
  const hint = !completed.date && !completed.time ? "날짜와 시간을 정해 주세요" : !completed.date ? "날짜를 정해 주세요" : !completed.time ? "시간을 입력해 주세요 (예: 18:30)" : "";
  return (
    <View style={styles.candidate}>
      <Text style={styles.title}>{candidate.title}</Text>
      <Text style={styles.caption}>{detail || "-"}</Text>
      {state === "ok" ? (
        <Text style={styles.success}>일정으로 등록했어요</Text>
      ) : (
        <>
          {needs.date ? <ChipRow label="날짜" options={DAY_CHIPS} value={day} onChange={onPickDay} /> : null}
          {needs.date && day === "custom" ? (
            <TextInput
              value={customText}
              onChangeText={(t) => onChangeCustom?.(formatDayInput(t))}
              placeholder="2026-11-05"
              placeholderTextColor={colors.placeholder}
              keyboardType="number-pad"
              maxLength={10}
              accessibilityLabel="일정 날짜 직접 입력(년-월-일)"
              style={styles.input}
            />
          ) : null}
          {needs.time ? (
            <TextInput
              value={timeText}
              onChangeText={(t) => onChangeTime?.(formatTimeInput(t))}
              placeholder="시간 18:30"
              placeholderTextColor={colors.placeholder}
              keyboardType="number-pad"
              maxLength={5}
              accessibilityLabel="일정 시간 입력(시:분)"
              style={styles.input}
            />
          ) : null}
          {hint ? <Text style={styles.note}>{hint}</Text> : null}
          {state && state !== "sending" ? (
            <Text style={styles.error} accessibilityRole="alert">
              {state}
            </Text>
          ) : null}
          <Button label={state === "sending" ? "등록하는 중..." : "일정으로 등록"} small variant="secondary" onPress={() => onRegister(completed)} disabled={!ready || state === "sending"} testID={testID} />
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
  note: { ...font.caption, color: colors.accent },
  input: { ...font.body, color: colors.text, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  error: { ...font.body, color: colors.danger },
});
