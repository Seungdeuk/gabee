import { Image } from "expo-image";
import { useEffect, useRef, useState } from "react";
import { Animated, Easing, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import mascot from "../../../../assets/images/gabee-mascot.png";

/** 초를 "12초" 또는 "1분 5초" 로 쓴다. */
export function formatSeconds(total) {
  const s = Math.max(0, Math.round(total));
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`;
}

function Dot({ delay }) {
  const v = useRef(new Animated.Value(0.25)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.delay(delay),
        Animated.timing(v, { toValue: 1, duration: 380, easing: Easing.out(Easing.quad), useNativeDriver: true }),
        Animated.timing(v, { toValue: 0.25, duration: 380, easing: Easing.in(Easing.quad), useNativeDriver: true }),
        Animated.delay(240 - delay),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [delay, v]);
  return <Animated.View style={[styles.dot, { opacity: v, transform: [{ scale: v.interpolate({ inputRange: [0.25, 1], outputRange: [0.8, 1.25] }) }] }]} />;
}

/** 깜빡이는 점 세 개. 일하는 중이라는 표시로 여러 곳에서 쓴다. */
export function PulseDots() {
  return (
    <View style={styles.dots}>
      <Dot delay={0} />
      <Dot delay={120} />
      <Dot delay={240} />
    </View>
  );
}

/**
 * 올린 파일을 읽는 동안 보이는 표시: 통통 튀는 가비, 깜빡이는 점, 지나간 시간.
 * 서버가 단계를 알려 주지 않아서 가짜 단계는 보이지 않고, 지금까지 걸린 시간과 보통 걸리는 시간만 알려 준다.
 * @param {{ since: number | null }} props since: 읽기를 시작한 시각(ms), 없으면 시간은 숨긴다
 */
export default function ReadingStatus({ since }) {
  const bounce = useRef(new Animated.Value(0)).current;
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(bounce, { toValue: -8, duration: 420, easing: Easing.out(Easing.quad), useNativeDriver: true }),
        Animated.timing(bounce, { toValue: 0, duration: 420, easing: Easing.in(Easing.quad), useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [bounce]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const seconds = since ? (now - since) / 1000 : null;
  return (
    <View style={styles.wrap} accessibilityLabel={`올린 파일을 읽는 중${seconds !== null ? `, ${formatSeconds(seconds)} 지났어요` : ""}`} accessibilityLiveRegion="polite">
      <Animated.View style={{ transform: [{ translateY: bounce }] }}>
        <Image source={mascot} style={styles.bee} contentFit="contain" />
      </Animated.View>
      <View style={styles.texts}>
        <View style={styles.line}>
          <Text style={styles.title}>읽는 중</Text>
          <PulseDots />
        </View>
        <Text style={styles.hint}>
          {seconds !== null ? `${formatSeconds(seconds)} 지났어요 · ` : ""}보통 5~30초 걸려요
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 4 },
  bee: { width: 56, height: 34 },
  texts: { gap: 2 },
  line: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 15, fontWeight: "700", color: colors.text },
  dots: { flexDirection: "row", gap: 4 },
  dot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.text },
  hint: { fontSize: 12, color: colors.textMuted },
});
