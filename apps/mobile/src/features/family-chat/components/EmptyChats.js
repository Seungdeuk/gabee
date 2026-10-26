import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, spacing } from "@/theme";

/**
 * 가족 그룹이 없을 때의 가운데 정렬 안내와 두 버튼.
 * @param {{ onCreate: () => void, onJoin: () => void }} props
 */
export default function EmptyChats({ onCreate, onJoin }) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>아직 가족이 없어요</Text>
      <Text style={styles.sub}>가족을 만들거나 초대 코드로 참여하면 대화를 시작할 수 있어요</Text>
      <View style={styles.buttons}>
        <Button label="가족 만들기" small onPress={onCreate} />
        <Button label="초대 코드로 참여" small variant="secondary" onPress={onJoin} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: "center", gap: spacing.md, paddingVertical: spacing.xxl, paddingHorizontal: spacing.lg },
  title: { ...font.section, color: colors.text },
  sub: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  buttons: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
});
