import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import Avatar from "@/shared/components/Avatar";
import Button from "@/shared/components/Button";
import { colors, font, fonts, radius } from "@/theme";

import PlayScreen from "../components/PlayScreen";
import { SCORE } from "../games";

const OPTIONS = ["할머니 댁", "제주도 여행", "돌잔치", "우리 집 거실"];
const MAX_SHRINK = 2; // 참가 점수가 10점이라 줄여 보기는 최대 2번
const START_ZOOM = 4;

/** 찰칵! 탐정단 맞히기: 확대된 사진 일부, 질문, 보기. "조금 줄여 보기"는 최대 2번(−5점씩). */
export default function PhotoGuessScreen() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const options = (() => {
    try {
      const o = JSON.parse(params.options ?? "[]");
      return o.length ? o : OPTIONS;
    } catch {
      return OPTIONS;
    }
  })();
  const question = params.question || "이 사진, 어디서 누구랑 찍었을까요?"; // 시안: 딸이 낸 문제(20자)
  const [shrunk, setShrunk] = useState(0);
  const [pick, setPick] = useState(null);
  const zoom = Math.max(1, START_ZOOM - shrunk);
  const left = MAX_SHRINK - shrunk;
  return (
    <PlayScreen
      title="찰칵! 탐정단"
      close
      footer={
        <>
          <Button label="답 보내기" disabled={pick == null} onPress={() => router.replace("/play/my-answer?kind=photo")} />
          <Text style={[styles.reveal, styles.center]}>내일 오후 2:10에 공개돼요</Text>
        </>
      }
    >
      <View style={styles.from}>
        <Avatar name="딸" userId="daughter" size={36} />
        <Text style={styles.fromText}>딸이 앨범에서 고른 사진이에요</Text>
      </View>
      <View style={styles.stage} accessibilityLabel={`사진의 일부를 ${zoom}배 확대해 보여 줘요`}>
        <Text style={styles.zoom}>{zoom}배 확대</Text>
        <Text style={styles.photoNote}>[가족 사진의 일부를 크게 보여 줌]</Text>
      </View>
      {/* 줄여 보기는 사진 바로 아래 오른쪽에 둔다: 누르고 위로 다시 올라가 볼 필요가 없게 */}
      <View style={styles.shrinkRow}>
        <Text style={styles.reveal}>최대 {MAX_SHRINK}번 · 남은 횟수 {left}번</Text>
        <Pressable
          onPress={() => setShrunk((x) => Math.min(MAX_SHRINK, x + 1))}
          disabled={left <= 0}
          accessibilityRole="button"
          accessibilityLabel={`조금 줄여 보기, 점수 ${SCORE.hintCost}점 줄어요. 남은 횟수 ${left}번`}
          style={[styles.shrinkBtn, shrunk === 1 && styles.shrink1, shrunk >= 2 && styles.shrink2]}
        >
          <Text style={styles.shrinkText}>조금 줄여 보기 (−{SCORE.hintCost}점)</Text>
        </Pressable>
      </View>
      <View style={styles.q}>
        <Text style={styles.qText} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
          {question}
        </Text>
      </View>
      <View style={styles.list}>
        {options.map((o) => (
          <Pressable key={o} onPress={() => setPick(o)} accessibilityRole="button" accessibilityState={{ selected: pick === o }} style={[styles.opt, pick === o && styles.optOn]}>
            <Text style={[styles.optText, pick === o && styles.optTextOn]}>{o}</Text>
          </Pressable>
        ))}
      </View>
    </PlayScreen>
  );
}

const styles = StyleSheet.create({
  from: { flexDirection: "row", alignItems: "center", gap: 10 },
  fromText: { ...font.bodyStrong, color: colors.text },
  stage: { height: 260, borderRadius: radius.card, backgroundColor: "#CDB9A3", alignItems: "center", justifyContent: "center" },
  zoom: { position: "absolute", left: 14, top: 12, paddingVertical: 4, paddingHorizontal: 10, borderRadius: 999, overflow: "hidden", backgroundColor: colors.background, fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  photoNote: { fontSize: 13, color: "#3A2719" },
  q: { paddingVertical: 14, paddingHorizontal: 14, borderRadius: radius.lg, backgroundColor: colors.surface, flexDirection: "row", alignItems: "center", gap: 10 },
  qText: { flex: 1, fontSize: 16, fontFamily: fonts.bold, color: colors.text },
  list: { gap: 10 },
  labelRow: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  typeLabel: { ...font.bodyStrong, color: colors.text },
  typeSub: { fontSize: 12, fontFamily: fonts.regular, color: colors.textSub, flexShrink: 1 },
  typeInput: { height: 48, paddingVertical: 0, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: "#E3CFB0", backgroundColor: colors.card, color: colors.text, fontSize: 16, fontFamily: fonts.regular },
  opt: { minHeight: 52, paddingHorizontal: 16, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, justifyContent: "center" },
  optOn: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  optText: { fontSize: 16, fontFamily: fonts.regular, color: colors.text },
  optTextOn: { fontFamily: fonts.bold },
  center: { textAlign: "center" },
  shrinkRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  shrinkBtn: { height: 36, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.card, alignItems: "center", justifyContent: "center" },
  shrink1: { backgroundColor: colors.surface, borderColor: colors.surface }, // 흰색 → 연한 노랑 → 가비 노랑 순서로 진해진다
  shrink2: { backgroundColor: colors.surfaceStrong, borderColor: colors.surfaceStrong },
  shrinkText: { fontSize: 13, fontFamily: fonts.bold, color: colors.text },
  reveal: { ...font.caption, color: colors.textSub },
});
