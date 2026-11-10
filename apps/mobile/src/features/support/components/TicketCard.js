import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { WAITING_NOTE, ticketView } from "../messages";

// 상태별 뱃지 색(바탕, 글자). 답변이 달린 것은 초록, 기다리는 것은 꿀색이다.
const BADGE = {
  answered: { backgroundColor: colors.successSoft, color: colors.success },
  closed: { backgroundColor: colors.successSoft, color: colors.success },
  working: { backgroundColor: colors.surfaceStrong, color: colors.text },
  waiting: { backgroundColor: colors.honeySoft, color: colors.accent },
};

/**
 * Q/A 줄 앞에 붙는 동그란 글자 표시.
 * @param {{ letter: "Q" | "A", tone: "q" | "a" }} props
 * @returns {import("react").ReactElement}
 */
function Mark({ letter, tone }) {
  return (
    <View style={[styles.mark, tone === "a" ? styles.markA : styles.markQ]}>
      <Text style={[styles.markText, tone === "a" && styles.markTextA]}>{letter}</Text>
    </View>
  );
}

/**
 * 보낸 문의·신고 한 건. 누르면 질문(Q)이 펼쳐지고, 답변이 있으면 답변(A)이 함께 보인다.
 * 답변이 달린 문의는 처음부터 펼쳐 둔다.
 * @param {{ row: object }} props TicketOut
 * @returns {import("react").ReactElement}
 */
export default function TicketCard({ row }) {
  const t = ticketView(row);
  const [open, setOpen] = useState(t.answered);
  const badge = BADGE[t.state];
  return (
    <View style={styles.card} testID={`ticket-${t.id}`}>
      <Pressable
        onPress={() => setOpen((v) => !v)}
        accessibilityRole="button"
        accessibilityLabel={`${t.kindLabel}, ${t.statusLabel}, ${t.title}`}
        accessibilityState={{ expanded: open }}
        style={styles.head}
      >
        <View style={styles.meta}>
          <Text style={[styles.badge, { backgroundColor: badge.backgroundColor, color: badge.color }]}>{t.statusLabel}</Text>
          <Text style={styles.metaText}>{t.kindLabel} · {t.sentOn}</Text>
        </View>
        <View style={styles.titleRow}>
          <Text style={styles.title} numberOfLines={open ? undefined : 2}>{t.title}</Text>
          <Ionicons name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
        </View>
      </Pressable>
      {open ? (
        <View style={styles.detail}>
          <View style={styles.line}>
            <Mark letter="Q" tone="q" />
            <Text style={styles.body}>{t.body}</Text>
          </View>
          {t.answered ? (
            <View style={styles.answer}>
              <View style={styles.line}>
                <Mark letter="A" tone="a" />
                <View style={styles.answerText}>
                  <Text style={styles.answerHead}>{t.answeredOn ? `고객센터 답변 · ${t.answeredOn}` : "고객센터 답변"}</Text>
                  <Text style={styles.body}>{t.answer}</Text>
                </View>
              </View>
            </View>
          ) : (
            <Text style={styles.waiting}>{WAITING_NOTE}</Text>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.card,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.divider,
    overflow: "hidden",
  },
  head: { gap: spacing.sm, paddingVertical: spacing.lg, paddingHorizontal: spacing.lg },
  meta: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  badge: {
    fontSize: 12,
    fontWeight: "700",
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  metaText: { ...font.caption, color: colors.textMuted },
  titleRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { ...font.cardTitle, color: colors.text, flex: 1 },
  detail: {
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
    paddingTop: spacing.lg,
  },
  line: { flexDirection: "row", gap: spacing.md, alignItems: "flex-start" },
  mark: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", marginTop: 1 },
  markQ: { backgroundColor: colors.surfaceStrong },
  markA: { backgroundColor: colors.accent },
  markText: { fontSize: 12, fontWeight: "700", color: colors.text },
  markTextA: { color: colors.onDark },
  body: { ...font.body, color: colors.textSub, flex: 1 },
  answer: { padding: spacing.md, borderRadius: 14, backgroundColor: colors.peachSoft },
  answerText: { flex: 1, gap: spacing.xs },
  answerHead: { ...font.caption, color: colors.accent, fontWeight: "700" },
  waiting: { ...font.caption, color: colors.textMuted },
});
