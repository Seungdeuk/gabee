import { StyleSheet, Text, View } from "react-native";
import Svg, { Polygon } from "react-native-svg";

import { hexPoints } from "@/shared/hexagon";
import { colors } from "@/theme";

const STROKE = 2;

/**
 * 이름 첫 글자를 보여 주는 육각형 아바타(가족 전체방용): 연한 꿀색 바탕에 복숭아색 둥근 테두리.
 * @param {{ name: string, size?: number }} props
 * @returns {import("react").ReactElement}
 */
export default function HexAvatar({ name, size = 56 }) {
  return (
    <View style={{ width: size, height: size }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={size} height={size}>
        <Polygon points={hexPoints(size, STROKE)} fill={colors.honeySoft} stroke={colors.peach} strokeWidth={STROKE} strokeLinejoin="round" />
      </Svg>
      <View style={styles.label}>
        <Text style={[styles.text, { fontSize: size * 0.34 }]}>{name.slice(0, 1)}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  label: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  text: { color: colors.text, fontWeight: "600" },
});
