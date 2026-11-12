import { Ionicons } from "@expo/vector-icons";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import { newsCardView } from "../../news/newsView";
import { BriefList, LeadArticle, SingleArticle } from "./NewsArticles";

/**
 * 가족 뉴스: 그 주 공유 기록으로 AI 가 만든 기사. 뉴스가 있으면 소식 수에 따라 짧은 카드 하나(1개)·메인 기사 + 단신(2~3개)·메인 기사 + 기사 목록(4개 이상)으로 펼치고,
 * 없음·만드는 중·실패 같은 상태는 같은 자리에 안내 카드로 보인다(기사를 억지로 채우지 않는다).
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

  if (v.kind === "ready") {
    return (
      <View style={styles.news}>
        {v.layout === "single" ? <SingleArticle article={v.lead} sources={v.sources} onOpenItem={onOpenItem} /> : null}
        {v.layout === "lead_brief" || v.layout === "lead_list" ? (
          <>
            <LeadArticle article={v.lead} sources={v.sources} onOpenItem={onOpenItem} />
            <BriefList
              briefs={v.briefs}
              sources={v.sources}
              mode={v.layout === "lead_list" ? "list" : "compact"}
              onOpenItem={onOpenItem}
            />
          </>
        ) : null}
        {v.layout === "none" ? <Text style={styles.message}>이 주에는 발행할 소식이 없어요.</Text> : null}
        {v.layout !== "none" ? <Text style={styles.note}>AI가 공유 기록으로 정리했어요. {v.note}</Text> : null}
      </View>
    );
  }

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <Text style={styles.label} accessibilityRole="header">가족 뉴스</Text>
        <Text style={styles.source}>AI가 공유 기록으로 정리해요</Text>
      </View>
      {v.kind === "loading" ? (
        <View style={styles.center} accessibilityRole="progressbar" accessibilityLabel="뉴스를 불러오는 중">
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : (
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
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  news: { gap: spacing.lg },
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
