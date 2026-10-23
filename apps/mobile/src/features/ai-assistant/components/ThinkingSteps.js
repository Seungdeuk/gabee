import { Ionicons } from "@expo/vector-icons";
import { useEffect, useRef, useState } from "react";
import { Animated, Easing, StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

import { formatSeconds, PulseDots } from "./ReadingStatus";

const STEPS = [
  { label: "기록 찾기", detail: "가족 기록에서" },
  { label: "답변 만들기", detail: "내용 정리" },
  { label: "마무리하기", detail: null },
];

/** 끝난 단계의 체크 표시: 처음 나타날 때 살짝 커졌다가 자리를 잡는다. */
function Check() {
  const scale = useRef(new Animated.Value(0.4)).current;
  useEffect(() => {
    Animated.spring(scale, { toValue: 1, friction: 4, tension: 160, useNativeDriver: true }).start();
  }, [scale]);
  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Ionicons name="checkmark" size={18} color={colors.success} />
    </Animated.View>
  );
}

/**
 * 가비가 답을 만드는 동안 보이는 진행 단계. 끝난 단계는 초록 체크(톡 튀어나옴), 지금 하는 단계는 깜빡이는 점,
 * 남은 단계는 빈 동그라미. 맨 아래에 지금까지 걸린 시간을 보여 준다.
 * 서버가 단계를 알려 주지 않아서 단계는 시간이 지나는 대로 넘어가는 표시용이고, 마지막 단계는 답이 올 때까지 머문다.
 * TODO: 서버가 단계를 알려 주면(예: 도구 호출 이름) 그 값을 보여 준다.
 */
export default function ThinkingSteps() {
  const [current, setCurrent] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const fade = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const timers = [setTimeout(() => setCurrent(1), 700), setTimeout(() => setCurrent(2), 1700)];
    const tick = setInterval(() => setSeconds((s) => s + 1), 1000);
    Animated.timing(fade, { toValue: 1, duration: 250, easing: Easing.out(Easing.quad), useNativeDriver: true }).start();
    return () => {
      timers.forEach(clearTimeout);
      clearInterval(tick);
    };
  }, [fade]);

  return (
    <Animated.View style={[styles.list, { opacity: fade }]} accessibilityLabel={`답변을 만드는 중, ${formatSeconds(seconds)} 지났어요`} accessibilityLiveRegion="polite">
      {STEPS.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <View key={step.label} style={styles.item}>
            <View style={styles.icon}>{done ? <Check /> : active ? <PulseDots /> : <View style={styles.ring} />}</View>
            <Text style={[styles.label, active && styles.labelActive, !done && !active && styles.labelWait]}>
              {step.label}
              {step.detail && (done || active) ? <Text style={styles.detail}> · {step.detail}</Text> : null}
            </Text>
          </View>
        );
      })}
      <Text style={styles.time}>{seconds >= 1 ? `${formatSeconds(seconds)} 지났어요` : "시작했어요"}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 14, paddingHorizontal: 4 },
  item: { flexDirection: "row", alignItems: "center", gap: 10 },
  icon: { width: 22, height: 22, alignItems: "center", justifyContent: "center" },
  ring: { width: 14, height: 14, borderRadius: 7, borderWidth: 1.8, borderColor: "#DCCDBF" },
  label: { fontSize: 14, color: colors.text },
  labelActive: { fontWeight: "700" },
  labelWait: { color: colors.textMuted },
  detail: { fontWeight: "400", color: colors.textMuted },
  time: { marginLeft: 32, fontSize: 12, color: colors.textMuted },
});
