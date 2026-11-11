import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { itemRoute, newsCardView, sentenceSources } from "../../news/newsView";

/**
 * 가족 뉴스 카드: 그 주 공유 기록으로 AI 가 만든 뉴스. 상태(없음·만드는 중·실패 등)마다 같은 자리에 안내를 보인다.
 * @param {{
 *   phase: "loading" | "loaded" | "error",
 *   offset: number,
 *   news: object | null,
 *   error?: unknown,
 *   creating: boolean,
 *   createError?: unknown,
 *   onCreate: () => void,
 *   onReload: () => void,
 *   onOpenItem: (route: string) => void,
 * }} props
 * @returns {import("react").ReactElement}
 */
export default function NewsCard({ phase, offset, news, error, creating, createError, onCreate, onReload, onOpenItem }) {
  const v = newsCardView({ phase, offset, news, error, creating, createError });
  const onAction = v.action === "create" ? onCreate : onReload;
  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.label} accessibilityRole="header">가족 뉴스</Text>
        <Text style={styles.source}>AI가 공유 기록으로 정리했어요</Text>
      </View>
      {v.kind === "loading" ? (
        <View style={styles.center} accessibilityRole="progressbar" accessibilityLabel="뉴스를 불러오는 중">
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : null}
      {v.kind === "ready" ? (
        <>
          <Text style={styles.title}>{v.title}</Text>
          {v.items.map((item, i) => {
            const route = itemRoute(item, v.sources);
            const labels = sentenceSources(item, v.sources)
              .map((s) => s.label)
              .join(" · ");
            const body = (
              <View style={styles.item}>
                <View style={styles.line}>
                  <View style={styles.dot} />
                  <Text style={styles.text}>{item.text}</Text>
                  {route ? <Ionicons name="chevron-forward" size={16} color={colors.accent} /> : null}
                </View>
                {labels ? <Text style={styles.evidence}>근거: {labels}</Text> : null}
              </View>
            );
            return route ? (
              <Pressable
                key={`${i}-${item.text}`}
                onPress={() => onOpenItem(route)}
                accessibilityRole="button"
                accessibilityLabel={`${item.text}${labels ? `. 근거: ${labels}` : ""}. 일정에서 확인하기`}
              >
                {body}
              </Pressable>
            ) : (
              <View key={`${i}-${item.text}`}>{body}</View>
            );
          })}
          <Text style={styles.note}>{v.note}</Text>
        </>
      ) : null}
      {v.kind !== "loading" && v.kind !== "ready" ? (
        <>
          {v.title ? <Text style={styles.title}>{v.title}</Text> : null}
          <Text style={styles.message}>{v.message}</Text>
          {v.notice ? (
            <View style={styles.notice} accessibilityRole="alert">
              <Ionicons name="alert-circle-outline" size={18} color={colors.danger} />
              <View style={styles.noticeText}>
                <Text style={styles.noticeTitle}>{v.notice.title}</Text>
                <Text style={styles.noticeMessage}>{v.notice.message}</Text>
              </View>
            </View>
          ) : null}
          {v.action ? (
            <View style={styles.action}>
              <Button label={v.actionLabel} variant="secondary" small onPress={onAction} disabled={v.busy} />
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  label: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily },
  source: { ...font.tab, color: colors.textMuted },
  center: { alignItems: "center", paddingVertical: spacing.lg },
  title: { ...font.cardTitle, color: colors.text },
  item: { gap: spacing.xs, minHeight: 44, justifyContent: "center" },
  line: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  dot: { width: 6, height: 6, marginTop: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.accent },
  text: { ...font.body, flex: 1, color: colors.text },
  evidence: { ...font.tab, color: colors.textMuted, marginLeft: spacing.lg },
  note: { ...font.tab, color: colors.textMuted },
  message: { ...font.body, color: colors.textSub },
  notice: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.card,
    backgroundColor: colors.dangerSoft,
  },
  noticeText: { flex: 1, gap: spacing.xs },
  noticeTitle: { ...font.caption, color: colors.text, fontFamily: font.bodyStrong.fontFamily },
  noticeMessage: { ...font.caption, color: colors.textSub },
  action: { alignSelf: "flex-start" },
});
