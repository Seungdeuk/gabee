import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

/**
 * 불러오기 실패 같은 알림 상자. 아이콘이 함께 있어 색만으로 구분하지 않는다. actionLabel 이 있으면 버튼이 붙는다.
 * @param {{ title: string, message?: string, actionLabel?: string, onAction?: () => void, actionDisabled?: boolean }} props
 * @returns {import("react").ReactElement}
 */
export default function NoticeBox({ title, message, actionLabel, onAction, actionDisabled = false }) {
  return (
    <View style={styles.box} accessibilityRole="alert">
      <View style={styles.head}>
        <Ionicons name="alert-circle-outline" size={20} color={colors.danger} />
        <Text style={styles.title}>{title}</Text>
      </View>
      {message ? <Text style={styles.message}>{message}</Text> : null}
      {actionLabel ? (
        <View style={styles.action}>
          <Button label={actionLabel} variant="secondary" small onPress={onAction} disabled={actionDisabled} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: spacing.sm, padding: spacing.lg, borderRadius: radius.card, backgroundColor: colors.dangerSoft },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { ...font.cardTitle, color: colors.text },
  message: { ...font.caption, color: colors.textSub },
  action: { alignSelf: "flex-start" },
});
