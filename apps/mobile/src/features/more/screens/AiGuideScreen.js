import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import IconButton from "@/shared/components/IconButton";
import Screen from "@/shared/components/Screen";
import { colors, font, radius, spacing } from "@/theme";

import GabeeBubble from "../components/report/GabeeBubble";
import {
  AI_GUIDE_CAUTION,
  AI_GUIDE_FEATURES,
  AI_GUIDE_HOW_TO,
  AI_GUIDE_INTRO,
  AI_GUIDE_PRIVACY,
  AI_GUIDE_SOURCES,
} from "../aiGuide";

/**
 * 제목과 카드 하나로 이루어진 안내 묶음.
 * @param {{ title: string, children: import("react").ReactNode }} props
 * @returns {import("react").ReactElement}
 */
function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle} accessibilityRole="header">
        {title}
      </Text>
      <View style={styles.card}>{children}</View>
    </View>
  );
}

/**
 * 아이콘과 글이 한 줄인 목록 항목. 색만으로 구분하지 않도록 아이콘을 함께 쓴다.
 * @param {{ icon: string, color: string, text: string }} props
 * @returns {import("react").ReactElement}
 */
function Line({ icon, color, text }) {
  return (
    <View style={styles.line}>
      <Ionicons name={icon} size={18} color={color} style={styles.lineIcon} />
      <Text style={styles.lineText}>{text}</Text>
    </View>
  );
}

/**
 * 마이 > 가비 AI 이용 안내: 가비가 하는 일, 부르는 방법, 참고하는 정보, 개인정보·외부 AI 처리 방식을 알려 주는 읽기 전용 화면.
 * @returns {import("react").ReactElement}
 */
export default function AiGuideScreen() {
  const router = useRouter();
  return (
    <Screen
      title="가비 AI 이용 안내"
      left={<IconButton name="chevron-back" label="뒤로" onPress={() => (router.canGoBack() ? router.back() : router.replace("/my"))} />}
    >
      <GabeeBubble text={AI_GUIDE_INTRO} />

      <Section title="가비가 해 주는 일">
        {AI_GUIDE_FEATURES.map((f) => (
          <View key={f.key} style={styles.feature}>
            <Ionicons name={f.icon} size={22} color={colors.accent} />
            <View style={styles.featureText}>
              <Text style={styles.featureTitle}>{f.title}</Text>
              <Text style={styles.sub}>{f.description}</Text>
            </View>
          </View>
        ))}
      </Section>

      <Section title="이렇게 불러요">
        {AI_GUIDE_HOW_TO.steps.map((s, i) => (
          <Text key={s} style={styles.lineText}>{`${i + 1}. ${s}`}</Text>
        ))}
        <View style={styles.examples}>
          {AI_GUIDE_HOW_TO.examples.map((e) => (
            <Text key={e} style={styles.example}>
              {e}
            </Text>
          ))}
        </View>
        <Text style={styles.sub}>{AI_GUIDE_HOW_TO.note}</Text>
      </Section>

      <Section title="가비가 참고하는 정보">
        {AI_GUIDE_SOURCES.used.map((t) => (
          <Line key={t} icon="checkmark-circle-outline" color={colors.success} text={t} />
        ))}
      </Section>

      <Section title="가비가 참고하지 않는 정보">
        {AI_GUIDE_SOURCES.unused.map((t) => (
          <Line key={t} icon="close-circle-outline" color={colors.danger} text={t} />
        ))}
      </Section>

      <Section title="개인정보와 외부 AI 처리">
        {AI_GUIDE_PRIVACY.map((t) => (
          <Line key={t} icon="shield-checkmark-outline" color={colors.accent} text={t} />
        ))}
      </Section>

      <Text style={styles.footer}>{AI_GUIDE_CAUTION}</Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  section: { gap: spacing.sm },
  sectionTitle: { ...font.cardTitle, color: colors.text },
  card: { gap: spacing.md, padding: spacing.lg, borderRadius: radius.card, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  feature: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  featureText: { flex: 1, gap: spacing.xs },
  featureTitle: { ...font.bodyStrong, color: colors.text },
  line: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  lineIcon: { marginTop: 2 },
  lineText: { ...font.body, color: colors.text, flex: 1 },
  sub: { ...font.caption, color: colors.textSub },
  examples: { gap: spacing.sm },
  example: { ...font.body, color: colors.text, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.surface },
  footer: { ...font.caption, color: colors.textMuted },
});
