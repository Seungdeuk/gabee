import { Image } from "expo-image";
import { StyleSheet, View } from "react-native";

import mascot from "../../../../assets/images/gabee-mascot.png";
import { colors } from "@/theme";

/** 가비(AI) 아바타: 앱의 대표 아이콘(꿀벌 마스코트)을 동그라미 안에 담아 사람 아바타와 구분한다. */
export default function AssistantAvatar({ size = 36 }) {
  return (
    <View style={[styles.circle, { width: size, height: size, borderRadius: size / 2 }]} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Image source={mascot} contentFit="cover" contentPosition={{ top: "20%", left: "62%" }} style={styles.image} />
    </View>
  );
}

const styles = StyleSheet.create({
  circle: { overflow: "hidden", backgroundColor: colors.honeySoft, borderWidth: 1, borderColor: colors.border },
  image: { width: "100%", height: "100%" },
});
