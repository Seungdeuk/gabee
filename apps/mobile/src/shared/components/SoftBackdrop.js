import { StyleSheet, View } from "react-native";
import Svg, { Defs, RadialGradient, Rect, Stop } from "react-native-svg";

import { colors } from "@/theme";

/**
 * 화면 뒤에 깔리는 은은한 배경: 크림 바탕에 복숭아색과 꿀색 빛이 번진다. 터치는 막지 않는다.
 * @returns {import("react").ReactElement}
 */
export default function SoftBackdrop() {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width="100%" height="100%">
        <Defs>
          <RadialGradient id="backdropPeach" cx="0.22" cy="0.55" r="0.75">
            <Stop offset="0" stopColor={colors.peach} stopOpacity={0.5} />
            <Stop offset="1" stopColor={colors.peach} stopOpacity={0} />
          </RadialGradient>
          <RadialGradient id="backdropHoney" cx="0.85" cy="0.3" r="0.7">
            <Stop offset="0" stopColor={colors.surfaceStrong} stopOpacity={0.9} />
            <Stop offset="1" stopColor={colors.surfaceStrong} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#backdropHoney)" />
        <Rect x="0" y="0" width="100%" height="100%" fill="url(#backdropPeach)" />
      </Svg>
    </View>
  );
}
