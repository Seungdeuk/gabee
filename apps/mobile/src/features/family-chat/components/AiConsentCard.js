import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import {
  CONSENT_CANCEL_LABEL,
  CONSENT_CONFIRM_LABEL,
  CONSENT_DETAILS,
  CONSENT_SUMMARY,
  CONSENT_TITLE,
  consentA11ySummary,
  detailsToggleLabel,
} from "../privacyCopy";

/**
 * 가족 AI 동의 안내 카드. 제목·요약은 항상 보이고 상세는 "자세히 보기"로 펼친다.
 * onConfirm 을 주면 "확인하고 켜기"/"취소" 버튼이 붙는다(켜기 직전 확인). 문구는 privacyCopy.js 에만 있다.
 * @param {{ onConfirm?: () => void, onCancel?: () => void, busy?: boolean, defaultOpen?: boolean }} props
 * @returns {JSX.Element}
 */
export default function AiConsentCard({ onConfirm, onCancel, busy = false, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <View style={styles.card} testID="chat-ai-consent">
      <Text style={styles.title} accessibilityRole="header">
        {CONSENT_TITLE}
      </Text>
      <View accessible accessibilityLabel={consentA11ySummary()} style={styles.summary}>
        {CONSENT_SUMMARY.map((line) => (
          <Text key={line} style={styles.sub}>
            {line}
          </Text>
        ))}
      </View>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        hitSlop={spacing.sm}
        style={styles.toggle}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={detailsToggleLabel(open)}
        testID="chat-ai-consent-toggle"
      >
        <Text style={styles.link}>{detailsToggleLabel(open)}</Text>
      </Pressable>
      {open ? (
        <View style={styles.details} testID="chat-ai-consent-details">
          {CONSENT_DETAILS.map((line) => (
            <Text key={line} style={styles.sub}>
              {line}
            </Text>
          ))}
        </View>
      ) : null}
      {onConfirm ? (
        <View style={styles.row}>
          <Button label={busy ? "켜는 중..." : CONSENT_CONFIRM_LABEL} small onPress={onConfirm} disabled={busy} testID="chat-ai-consent-confirm" />
          <Button label={CONSENT_CANCEL_LABEL} small variant="secondary" onPress={onCancel} disabled={busy} testID="chat-ai-consent-cancel" />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.xs, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md },
  title: { ...font.cardTitle, color: colors.text },
  summary: { gap: spacing.xs },
  details: { gap: spacing.xs },
  sub: { ...font.caption, color: colors.textSub },
  toggle: { minHeight: 44, justifyContent: "center" },
  link: { ...font.bodyStrong, color: colors.accent },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
});
