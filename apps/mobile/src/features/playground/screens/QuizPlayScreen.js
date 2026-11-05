import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";

// 엄마가 낸 골든벨 3문제 (시안 데이터)
const QUESTIONS = [
  { kind: "OX", q: "엄마 생신은 12월이다", options: ["O", "X"] },
  { kind: "선택", q: "아빠가 제일 좋아하는 반찬은?", options: ["계란말이", "멸치볶음", "김치찌개", "잡채"] },
  { kind: "선택", q: "우리 가족이 처음 같이 간 여행지는?", options: ["제주도", "강릉", "부산", "여수"] },
];

/** 가족 골든벨 풀기: 한 문제씩 고르고 "다음 문제", 마지막에는 "답 보내기". */
export default function QuizPlayScreen() {
  const router = useRouter();
  const [i, setI] = useState(0);
  const [picks, setPicks] = useState({}); // 처음에는 아무것도 골라져 있지 않다
  const cur = QUESTIONS[i];
  const last = i === QUESTIONS.length - 1;
  const next = () => (last ? router.replace("/play/quiz-result") : setI(i + 1));
  return (
    <PlayScreen
      title={`${i + 1} / ${QUESTIONS.length} 문제`}
      close
      footer={
        <>
          <Text style={styles.reveal}>내일 오후 2:10 공개</Text>
          <Button label={last ? "답 보내기" : "다음 문제"} disabled={picks[i] == null} onPress={next} />
        </>
      }
    >
      <View style={styles.dots}>
        {QUESTIONS.map((_, k) => (
          <View key={k} style={[styles.dot, k <= i && styles.dotOn]} />
        ))}
      </View>
      <View style={styles.from}>
        <Avatar name="엄마" userId="mom" size={36} />
        <Text style={styles.fromText}>엄마가 낸 문제</Text>
      </View>
      <View style={styles.card}>
        <Text style={styles.kind}>{cur.kind}</Text>
        <Text style={styles.q}>{cur.q}</Text>
      </View>
      <View style={cur.kind === "OX" ? styles.oxRow : styles.list}>
        {cur.options.map((o, k) => {
          const on = picks[i] === k;
          return (
            <Pressable
              key={o}
              onPress={() => setPicks((p) => ({ ...p, [i]: k }))}
              accessibilityRole="button"
              accessibilityState={{ selected: on }}
              style={[styles.opt, cur.kind === "OX" && styles.oxOpt, on && styles.optOn]}
            >
              <Text style={[styles.optText, on && styles.optTextOn]}>{o}</Text>
            </Pressable>
          );
        })}
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  dots: { flexDirection: "row", gap: 6 },
  dot: { flex: 1, height: 6, borderRadius: 3, backgroundColor: colors.border },
  dotOn: { backgroundColor: colors.accent },
  from: { flexDirection: "row", alignItems: "center", gap: 10 },
  fromText: { ...font.bodyStrong, color: colors.text },
  card: { padding: 20, borderRadius: radius.card, backgroundColor: colors.surface, gap: 8 },
  kind: { fontSize: 12, fontFamily: fonts.bold, color: colors.accent },
  q: { fontSize: 20, lineHeight: 30, fontFamily: fonts.bold, color: colors.text },
  list: { gap: 10 },
  oxRow: { flexDirection: "row", gap: 10 },
  opt: { minHeight: 56, paddingHorizontal: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, justifyContent: "center" },
  oxOpt: { flex: 1, height: 88, alignItems: "center" },
  optOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  optText: { fontSize: 16, fontFamily: fonts.regular, color: colors.text },
  optTextOn: { fontFamily: fonts.bold },
  reveal: { ...font.caption, color: colors.textSub, textAlign: "center" },
});
