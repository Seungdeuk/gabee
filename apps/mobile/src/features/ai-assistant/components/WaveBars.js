import { useEffect, useState } from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";

import { colors } from "@/theme";

const HEIGHTS = [12, 24, 38, 44, 30, 18, 10]; // 디자인의 막대 높이

/** 음성 입력 중임을 보여 주는 막대 7개. 막대가 서로 다른 박자로 커졌다 작아진다. */
export default function WaveBars() {
  const [scales] = useState(() => HEIGHTS.map(() => new Animated.Value(0.45)));

  useEffect(() => {
    const loops = scales.map((v, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.timing(v, { toValue: 1, duration: 420 + i * 60, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
          Animated.timing(v, { toValue: 0.45, duration: 420 + i * 60, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        ]),
      ),
    );
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, [scales]);

  return (
    <View style={styles.row} accessibilityLabel="듣고 있어요">
      {HEIGHTS.map((h, i) => (
        <Animated.View key={i} style={[styles.bar, { height: h, transform: [{ scaleY: scales[i] }] }]} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 5, height: 44 },
  bar: { width: 5, borderRadius: 3, backgroundColor: colors.peach },
});
