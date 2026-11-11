import { Ionicons } from "@expo/vector-icons";
import { StyleSheet, View } from "react-native";
import Svg, { Polygon } from "react-native-svg";

import { hexPoints } from "@/shared/hexagon";
import { colors } from "@/theme";

const STROKE = 2;
const ICON_RATIO = 0.5; // 육각형 안에서 아이콘이 차지하는 크기(꼭짓점에 닿지 않게)

/**
 * 가족 전체방용 육각형 아바타: 연한 꿀색 바탕에 복숭아색 둥근 테두리, 가운데에 가족(people) 아이콘.
 * @param {{ size?: number }} props
 * @returns {import("react").ReactElement}
 */
export default function HexAvatar({ size = 56 }) {
  return (
    <View style={{ width: size, height: size }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={size} height={size}>
        <Polygon points={hexPoints(size, STROKE)} fill={colors.honeySoft} stroke={colors.peach} strokeWidth={STROKE} strokeLinejoin="round" />
      </Svg>
      <View style={styles.label}>
        <Ionicons name="people" size={size * ICON_RATIO} color={colors.text} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  label: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
});
