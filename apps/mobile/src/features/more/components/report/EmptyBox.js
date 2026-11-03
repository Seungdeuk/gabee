import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 비어 있을 때 보여 주는 안내 상자. actionLabel 이 있으면 버튼이 붙는다.
 * @param {{ title: string, description: string, actionLabel?: string, onAction?: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function EmptyBox({ title, description, actionLabel, onAction }) {
  return (
    <View style={styles.box}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.description}>{description}</Text>
      {actionLabel ? <Button label={actionLabel} variant="secondary" small onPress={onAction} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.xxl,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  title: { ...font.cardTitle, color: colors.text, textAlign: "center" },
  description: { ...font.caption, color: colors.textMuted, textAlign: "center", marginBottom: spacing.sm },
});
