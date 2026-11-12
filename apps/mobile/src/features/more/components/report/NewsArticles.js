import { Ionicons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, font, radius, spacing } from "@/theme";

import { LEAD_KICKER, SECTION_LABEL, itemRoute, sentenceSources } from "../../news/newsView";

/**
 * 기사의 근거 이름들("학교 공연 · 분리수거"). 없으면 빈 문자열.
 * @param {{ item: { source_ids?: string[] } }} article
 * @param {{ id: string, label: string }[]} sources
 * @returns {string}
 */
function evidenceOf(article, sources) {
  return sentenceSources(article.item, sources)
    .map((s) => s.label)
    .join(" · ");
}

/**
 * 날짜와 근거를 한 줄로("11월 3일(화) · 근거: 학교 공연"). 둘 다 없으면 빈 문자열.
 * @param {{ date: string | null, item: { source_ids?: string[] } }} article
 * @param {{ id: string, label: string }[]} sources
 * @returns {string}
 */
function metaLine(article, sources) {
  const evidence = evidenceOf(article, sources);
  return [article.date, evidence ? `근거: ${evidence}` : ""].filter(Boolean).join(" · ");
}

/**
 * 기사 한 편을 눌러서 갈 곳이 있으면 Pressable 로, 없으면 View 로 감싼다. children 은 눌러서 갈 수 있는지(boolean)를 받아 그린다.
 * 읽기 이름은 화면에 보이는 내용과 같게 만든다(분류·제목·보이는 본문·날짜·근거). 본문을 그리지 않는 단신은 showBody=false.
 * @param {{ article: object, sources: object[], showBody?: boolean, onOpenItem: (route: string) => void, children: (tappable: boolean) => import("react").ReactNode }} props
 * @returns {import("react").ReactElement}
 */
function Tappable({ article, sources, showBody = true, onOpenItem, children }) {
  const route = itemRoute(article.item, sources);
  if (!route) return <View>{children(false)}</View>;
  const meta = metaLine(article, sources);
  const parts = [article.category, article.headline, showBody ? article.body : "", meta].filter(Boolean);
  return (
    <Pressable
      onPress={() => onOpenItem(route)}
      accessibilityRole="button"
      accessibilityLabel={`${parts.join(". ")}. 일정에서 확인하기`}
    >
      {children(true)}
    </Pressable>
  );
}

/**
 * 메인 기사: 이 주의 가장 큰 소식 하나. 헤드라인을 크게, (제목과 다른 말일 때만) 본문, 날짜와 근거를 아래에 둔다.
 * @param {{ article: { headline: string, body: string, category: string | null, date: string | null, item: object }, sources: object[], onOpenItem: (route: string) => void }} props
 * @returns {import("react").ReactElement}
 */
export function LeadArticle({ article, sources, onOpenItem }) {
  const meta = metaLine(article, sources);
  return (
    <Tappable article={article} sources={sources} onOpenItem={onOpenItem}>
      {(tappable) => (
        <View style={styles.lead}>
          <View style={styles.kickerRow}>
            <Ionicons name="newspaper-outline" size={16} color={colors.accent} />
            <Text style={styles.kicker}>{LEAD_KICKER}{article.category ? ` · ${article.category}` : ""}</Text>
          </View>
          <View style={styles.headRow}>
            <Text style={styles.leadHeadline} accessibilityRole="header">
              {article.headline}
            </Text>
            {tappable ? <Ionicons name="chevron-forward" size={18} color={colors.accent} /> : null}
          </View>
          {article.body ? <Text style={styles.leadBody}>{article.body}</Text> : null}
          {meta ? <Text style={styles.meta}>{meta}</Text> : null}
        </View>
      )}
    </Tappable>
  );
}

/**
 * 소식이 하나뿐일 때의 짧은 기사 카드(메인 기사 틀을 쓰지 않는다). 제목·날짜·근거, 본문은 제목과 다른 말일 때만.
 * @param {{ article: { headline: string, body: string, category: string | null, date: string | null, item: object }, sources: object[], onOpenItem: (route: string) => void }} props
 * @returns {import("react").ReactElement}
 */
export function SingleArticle({ article, sources, onOpenItem }) {
  const meta = metaLine(article, sources);
  return (
    <View style={styles.single}>
      <Text style={styles.sectionLabel} accessibilityRole="header">
        {SECTION_LABEL}
      </Text>
      <Tappable article={article} sources={sources} onOpenItem={onOpenItem}>
        {(tappable) => (
          <View style={styles.headRow}>
            <View style={styles.briefText}>
              {article.category ? <Text style={styles.briefCategory}>{article.category}</Text> : null}
              <Text style={styles.singleHeadline}>{article.headline}</Text>
              {article.body ? <Text style={styles.briefBody}>{article.body}</Text> : null}
              {meta ? <Text style={styles.meta}>{meta}</Text> : null}
            </View>
            {tappable ? <Ionicons name="chevron-forward" size={16} color={colors.accent} /> : null}
          </View>
        )}
      </Tappable>
    </View>
  );
}

/**
 * 소식 목록. compact(2~3개 단신)는 제목 + 날짜·근거만, list(4개 이상 기사 목록)는 제목 + 본문(제목과 다른 말일 때) + 날짜·근거.
 * @param {{ briefs: { headline: string, body: string, category: string | null, date: string | null, item: object }[], sources: object[], mode: "compact" | "list", onOpenItem: (route: string) => void }} props
 * @returns {import("react").ReactElement | null}
 */
export function BriefList({ briefs, sources, mode, onOpenItem }) {
  if (briefs.length === 0) return null;
  return (
    <View style={styles.briefs}>
      <Text style={styles.sectionLabel} accessibilityRole="header">
        {SECTION_LABEL}
      </Text>
      {briefs.map((article, i) => {
        const meta = metaLine(article, sources);
        return (
          <Tappable
            key={`${i}-${article.headline}`}
            article={article}
            sources={sources}
            showBody={mode === "list"}
            onOpenItem={onOpenItem}
          >
            {(tappable) => (
              <View style={[styles.brief, i > 0 ? styles.briefBorder : null]}>
                <View style={styles.headRow}>
                  <View style={styles.briefText}>
                    {article.category ? <Text style={styles.briefCategory}>{article.category}</Text> : null}
                    <Text style={styles.briefHeadline}>{article.headline}</Text>
                    {mode === "list" && article.body ? <Text style={styles.briefBody}>{article.body}</Text> : null}
                    {meta ? <Text style={styles.meta}>{meta}</Text> : null}
                  </View>
                  {tappable ? <Ionicons name="chevron-forward" size={16} color={colors.accent} /> : null}
                </View>
              </View>
            )}
          </Tappable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  lead: {
    gap: spacing.sm,
    padding: spacing.lg,
    borderRadius: radius.card,
    backgroundColor: colors.honeySoft,
    minHeight: 44,
  },
  single: {
    gap: spacing.sm,
    padding: spacing.lg,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    minHeight: 44,
  },
  kickerRow: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  kicker: { ...font.caption, color: colors.accent, fontFamily: font.bodyStrong.fontFamily },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  leadHeadline: { ...font.h1, flex: 1, color: colors.text },
  leadBody: { ...font.body, color: colors.textSub },
  singleHeadline: { ...font.section, color: colors.text },
  meta: { ...font.caption, color: colors.textMuted },
  briefs: { gap: spacing.xs },
  sectionLabel: { ...font.caption, color: colors.textMuted, fontFamily: font.bodyStrong.fontFamily },
  brief: { paddingVertical: spacing.md, minHeight: 44, justifyContent: "center" },
  briefBorder: { borderTopWidth: 1, borderTopColor: colors.divider },
  briefText: { flex: 1, gap: spacing.xs },
  briefCategory: { ...font.tab, color: colors.accent },
  briefHeadline: { ...font.cardTitle, color: colors.text },
  briefBody: { ...font.body, color: colors.textSub },
});
