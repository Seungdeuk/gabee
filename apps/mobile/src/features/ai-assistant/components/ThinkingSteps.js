import { Ionicons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/theme";

const STEPS = [
  { label: "기록 찾기", detail: "가족 기록에서" },
  { label: "답변 만들기", detail: "내용 정리" },
  { label: "마무리하기", detail: null },
];

/**
 * 가비가 답을 만드는 동안 보이는 진행 단계. 끝난 단계는 초록 체크, 지금 하는 단계는 굵게 점 세 개, 남은 단계는 빈 동그라미.
 * TODO: 서버가 단계를 알려 주면(예: 도구 호출 이름) 그 값을 보여 준다. 지금은 시간이 지나는 대로 넘어가는 표시용이다.
 */
export default function ThinkingSteps() {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    const timers = [setTimeout(() => setCurrent(1), 700), setTimeout(() => setCurrent(2), 1700)];
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <View style={styles.list} accessibilityLabel="답변을 만드는 중">
      {STEPS.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <View key={step.label} style={styles.item}>
            <View style={styles.icon}>
              {done ? (
                <Ionicons name="checkmark" size={18} color={colors.success} />
              ) : active ? (
                <View style={styles.dots}>
                  <View style={styles.dot} />
                  <View style={[styles.dot, { opacity: 0.6 }]} />
                  <View style={[styles.dot, { opacity: 0.3 }]} />
                </View>
              ) : (
                <View style={styles.ring} />
              )}
            </View>
            <Text style={[styles.label, active && styles.labelActive, !done && !active && styles.labelWait]}>
              {step.label}
              {step.detail && (done || active) ? <Text style={styles.detail}> · {step.detail}</Text> : null}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 14, paddingHorizontal: 4 },
  item: { flexDirection: "row", alignItems: "center", gap: 10 },
  icon: { width: 22, height: 22, alignItems: "center", justifyContent: "center" },
  dots: { flexDirection: "row", gap: 3 },
  dot: { width: 4, height: 4, borderRadius: 2, backgroundColor: colors.text },
  ring: { width: 14, height: 14, borderRadius: 7, borderWidth: 1.8, borderColor: "#DCCDBF" },
  label: { fontSize: 14, color: colors.text },
  labelActive: { fontWeight: "700" },
  labelWait: { color: colors.textMuted },
  detail: { fontWeight: "400", color: colors.textMuted },
});
