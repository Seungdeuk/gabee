import { Image } from "expo-image";
import { StyleSheet, Text, View } from "react-native";

import Button from "@/shared/components/Button";
import { colors, font, radius, spacing } from "@/theme";

import mascot from "../../../../../assets/images/gabee-mascot.png";

/**
 * 가족이 없을 때의 안내: 가비 이미지, 설명, 가족 만들기·참여 버튼.
 * @param {{ onCreate: () => void, onJoin: () => void }} props
 * @returns {import("react").ReactElement}
 */
export default function NoFamilyBox({ onCreate, onJoin }) {
  return (
    <View style={styles.box}>
      <Image source={mascot} style={styles.mascot} contentFit="cover" accessibilityLabel="가비" />
      <Text style={styles.title}>{"가족을 만들거나\n기존 가족에 참여해 주세요"}</Text>
      <Text style={styles.description}>가족이 생기면 한 주 동안 함께 한 일을 가비가 모아 드려요.</Text>
      <View style={styles.buttons}>
        <Button label="우리 가족 만들기" onPress={onCreate} />
        <Button label="초대 코드로 참여하기" variant="secondary" onPress={onJoin} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { alignItems: "center", gap: spacing.md, paddingTop: spacing.xxl },
  mascot: { width: 96, height: 96, borderRadius: radius.card },
  title: { ...font.title, color: colors.text, textAlign: "center" },
  description: { ...font.caption, color: colors.textMuted, textAlign: "center" },
  buttons: { alignSelf: "stretch", gap: spacing.sm, marginTop: spacing.md },
});
