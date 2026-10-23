import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import Card from "@/shared/components/Card";
import { colors, font } from "@/theme";

import { summarizeChat } from "../api";
import { chatErrorMessage, summaryCaption } from "../messages";

/**
 * 가족 대화 자동 요약 카드. "요약하기"를 누를 때만 최근 대화가 AI 로 보내지고, 결과는 이 화면에만 보인다(저장되지 않는다).
 */
export default function SummaryCard() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await summarizeChat());
    } catch (e) {
      setResult(null);
      setError(chatErrorMessage(e));
    }
    setBusy(false);
  };

  return (
    <Card tone="blue" testID="chat-summary">
      <Text style={styles.title}>AI 대화 요약</Text>
      <Text style={styles.sub}>긴 가족 대화를 핵심만 짧게 정리해 드려요. 누를 때만 최근 대화가 AI로 전달되고, 요약은 저장되지 않아요.</Text>
      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      {result ? (
        <View style={styles.result}>
          <Text style={styles.summary} selectable testID="chat-summary-text">
            {result.summary}
          </Text>
          <Text style={styles.caption}>{summaryCaption(result)}</Text>
        </View>
      ) : null}
      <Button label={busy ? "요약하는 중..." : result ? "다시 요약하기" : "최근 대화 요약하기"} small onPress={run} disabled={busy} testID="chat-summary-run" />
    </Card>
  );
}

const styles = StyleSheet.create({
  title: { ...font.cardTitle, color: colors.text },
  sub: { ...font.caption, color: colors.textSub },
  error: { ...font.body, color: colors.danger },
  result: { gap: 6, backgroundColor: colors.card, borderRadius: 14, padding: 12 },
  summary: { ...font.body, color: colors.text },
  caption: { ...font.caption, color: colors.textMuted },
});
